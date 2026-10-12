// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const stopProject = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/api")>();
  return { ...real, api: { ...real.api, stopProject: (...args: unknown[]) => stopProject(...args) } };
});

import { StopProjectButton } from "@/views/ProjectDetailView";

afterEach(() => {
  cleanup();
  stopProject.mockReset();
});

describe("StopProjectButton", () => {
  it("asks for confirmation before stopping, then calls the API once", async () => {
    stopProject.mockResolvedValue({ cancelled_tasks: 5, project: {} });
    const onStopped = vi.fn();
    render(<StopProjectButton projectId="P-1" onStopped={onStopped} />);

    fireEvent.click(screen.getByRole("button", { name: "Stop project" }));
    expect(stopProject).not.toHaveBeenCalled();                    // one click never stops anything
    expect(screen.getByText("Stop all work on this project?")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Yes, stop now" }));
    await waitFor(() => expect(onStopped).toHaveBeenCalledTimes(1));
    expect(stopProject).toHaveBeenCalledWith("P-1");
  });

  it("can be backed out of without stopping", () => {
    render(<StopProjectButton projectId="P-1" onStopped={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Stop project" }));
    fireEvent.click(screen.getByRole("button", { name: "Keep running" }));
    expect(stopProject).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Stop project" })).toBeTruthy();
  });

  it("shows the API error and stays on the page when stopping fails", async () => {
    stopProject.mockRejectedValue(new Error("project P-1 is already COMPLETED"));
    const onStopped = vi.fn();
    render(<StopProjectButton projectId="P-1" onStopped={onStopped} />);
    fireEvent.click(screen.getByRole("button", { name: "Stop project" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, stop now" }));
    await waitFor(() => expect(screen.getByText(/already COMPLETED/)).toBeTruthy());
    expect(onStopped).not.toHaveBeenCalled();
  });
});
