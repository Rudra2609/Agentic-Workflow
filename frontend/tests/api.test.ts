// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";

import { ApiError, UNAUTHORIZED_EVENT, createApiClient, csrfToken, describeErrorBody } from "@/lib/api";

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

function setup(impl: (url: string, init: RequestInit) => Promise<Response>) {
  const fetchMock = vi.fn(impl as unknown as typeof fetch);
  const client = createApiClient({ baseUrl: "http://api.test:8000/", fetch: fetchMock, timeoutMs: 1000 });
  return { client, fetchMock };
}

describe("api client: success", () => {
  it("GETs /api/projects and returns parsed JSON", async () => {
    const projects = [{ project_id: "p1", name: "Demo", state: "CREATED" }];
    const { client, fetchMock } = setup(async () => jsonResponse(projects));

    await expect(client.listProjects()).resolves.toEqual(projects);

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("http://api.test:8000/api/projects");
    expect(init?.method).toBe("GET");
  });

  it("POSTs JSON bodies and encodes path segments", async () => {
    const { client, fetchMock } = setup(async () => jsonResponse({ project_id: "a b", state: "EXECUTING" }));
    await client.decideApproval("a b", true, "  looks good  ");

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("http://api.test:8000/api/projects/a%20b/approval");
    expect(init?.method).toBe("POST");
    expect((init?.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(JSON.parse(String(init?.body))).toEqual({ approved: true, comment: "looks good" });
  });

  it("creates projects with the auto-approve flag and stops them", async () => {
    const { client, fetchMock } = setup(async () => jsonResponse({ project_id: "p1" }));
    await client.createProject("Lab 7", true);
    await client.stopProject("p 1");
    const [createUrl, createInit] = fetchMock.mock.calls[0]!;
    expect(createUrl).toBe("http://api.test:8000/api/projects");
    expect(JSON.parse(String(createInit?.body))).toEqual({ name: "Lab 7", auto_approve: true, goal: null, cloud_ok: true });
    const [stopUrl, stopInit] = fetchMock.mock.calls[1]!;
    expect(stopUrl).toBe("http://api.test:8000/api/projects/p%201/stop");
    expect(stopInit?.method).toBe("POST");
    expect(JSON.parse(String(stopInit?.body))).toEqual({ reason: "stopped by user" });
  });

  it("can keep a new project on this computer", async () => {
    const { client, fetchMock } = setup(async () => jsonResponse({ project_id: "p1" }));
    await client.createProject("Private", false, "Summarise my notes", false);
    expect(JSON.parse(String(fetchMock.mock.calls[0]![1]?.body))).toMatchObject({ goal: "Summarise my notes", cloud_ok: false });
  });

  it("sends the event query as after_seq / project_id", async () => {
    const { client, fetchMock } = setup(async () => jsonResponse([]));
    await client.listEvents({ projectId: "p1", afterSeq: 41 });
    expect(fetchMock.mock.calls[0]![0]).toBe("http://api.test:8000/api/events?project_id=p1&after_seq=41");
  });

  it("uploads documents as multipart form data", async () => {
    const { client, fetchMock } = setup(async () => jsonResponse({ artifact: {}, filename: "req.md" }, { status: 201 }));
    await client.uploadDocument("p1", new Blob(["# hi"], { type: "text/markdown" }), "req.md");

    const init = fetchMock.mock.calls[0]![1]!;
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBeInstanceOf(Blob);
    expect((init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });
});

describe("api client: sessions", () => {
  it("reads the CSRF cookie and sends it only on state-changing requests", async () => {
    expect(csrfToken("a=1; hmap_csrf=abc%2Fdef; b=2")).toBe("abc/def");
    document.cookie = "hmap_csrf=tok123";
    const { client, fetchMock } = setup(async () => jsonResponse({}));
    await client.listProjects();
    await client.updateProject("p1", { archived: true });
    await client.deleteProject("p1");
    const [getUrl, getInit] = fetchMock.mock.calls[0]!;
    expect(getUrl).toBe("http://api.test:8000/api/projects");
    expect((getInit!.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
    expect((fetchMock.mock.calls[1]![1]!.headers as Record<string, string>)["X-CSRF-Token"]).toBe("tok123");
    expect(fetchMock.mock.calls[1]![1]!.method).toBe("PATCH");
    expect(fetchMock.mock.calls[2]![1]!.method).toBe("DELETE");
    document.cookie = "hmap_csrf=; max-age=0";
  });

  it("signals an expired session, but not for the sign-in calls themselves", async () => {
    const seen = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, seen);
    const { client } = setup(async () => jsonResponse({ detail: "Sign in to continue." }, { status: 401 }));
    await expect(client.listProjects()).rejects.toMatchObject({ status: 401 });
    await expect(client.login("a@b.co", "x")).rejects.toMatchObject({ status: 401 });
    expect(seen).toHaveBeenCalledTimes(1);
    window.removeEventListener(UNAUTHORIZED_EVENT, seen);
  });

  it("uses form-field errors from the accounts API", async () => {
    const { client } = setup(async () =>
      jsonResponse({ detail: { message: "Use at least 10 characters.", field: "password" } }, { status: 400 }),
    );
    const err = (await client.register("A", "a@b.co", "x").catch((e: unknown) => e)) as ApiError;
    expect(err.message).toBe("Use at least 10 characters.");
    expect(err.field).toBe("password");
  });

  it("treats 204 No Content as success", async () => {
    const { client } = setup(async () => new Response(null, { status: 204 }));
    await expect(client.logout()).resolves.toBeUndefined();
  });
});

describe("api client: errors", () => {
  it("surfaces FastAPI's 4xx detail message", async () => {
    const { client } = setup(async () => jsonResponse({ detail: "project nope not found" }, { status: 404, statusText: "Not Found" }));

    const err = await client.getProject("nope").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    const apiErr = err as ApiError;
    expect(apiErr.message).toBe("project nope not found");
    expect(apiErr.status).toBe(404);
    expect(apiErr.kind).toBe("http");
    expect(apiErr.isNotFound).toBe(true);
  });

  it("joins 422 validation errors into one readable line", async () => {
    const detail = [
      { loc: ["body", "name"], msg: "String should have at least 1 character", type: "string_too_short" },
      { loc: ["query", "x"], msg: "Field required", type: "missing" },
    ];
    const { client } = setup(async () => jsonResponse({ detail }, { status: 422 }));
    await expect(client.createProject("")).rejects.toThrow(
      "name: String should have at least 1 character; query.x: Field required",
    );
  });

  it("falls back to the status line when the body is empty", async () => {
    const { client } = setup(async () => new Response("", { status: 409, statusText: "Conflict" }));
    await expect(client.cancelTask("t1")).rejects.toThrow("409 Conflict");
  });

  it("turns a network failure into a helpful 'API not reachable' error", async () => {
    const { client } = setup(async () => {
      throw new TypeError("Failed to fetch");
    });
    const err = (await client.listAgents().catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.kind).toBe("network");
    expect(err.status).toBeNull();
    expect(err.message).toContain("http://api.test:8000");
    expect(err.message).toContain("not reachable");
    expect(err.message).toContain("uvicorn");
  });

  it("reports timeouts as network errors", async () => {
    const client = createApiClient({
      baseUrl: "http://api.test:8000",
      timeoutMs: 20,
      fetch: ((_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        })) as unknown as typeof fetch,
    });
    await expect(client.listProjects()).rejects.toMatchObject({ kind: "network", message: expect.stringContaining("timed out") });
  });

  it("rejects a 2xx non-JSON body as a parse error", async () => {
    const { client } = setup(async () => new Response("<html>proxy page</html>", { status: 200 }));
    await expect(client.listProjects()).rejects.toMatchObject({ kind: "parse" });
  });

  it("describeErrorBody handles odd shapes", () => {
    expect(describeErrorBody({ detail: { code: "X" } }, "fb")).toBe('{"code":"X"}');
    expect(describeErrorBody("plain text", "fb")).toBe("plain text");
    expect(describeErrorBody(undefined, "fb")).toBe("fb");
  });
});
