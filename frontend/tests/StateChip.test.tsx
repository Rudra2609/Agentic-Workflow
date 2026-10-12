// @vitest-environment happy-dom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { TASK_STATE_TONES, TONE_CLASSES, TaskStateChip } from "@/components/StateChip";
import { humanize } from "@/lib/format";
import { TASK_STATES, TERMINAL_TASK_STATES } from "@/lib/types";

afterEach(() => cleanup());

describe("TaskStateChip", () => {
  it("has a tone for every TaskState and nothing else", () => {
    expect(Object.keys(TASK_STATE_TONES).sort()).toEqual([...TASK_STATES].sort());
  });

  it.each(TASK_STATES)("renders %s with its mapped colour and a readable label", (state) => {
    render(<TaskStateChip state={state} />);
    const chip = screen.getByText(humanize(state));
    expect(chip.getAttribute("data-state")).toBe(state);
    const tone = TASK_STATE_TONES[state];
    expect(chip.getAttribute("data-tone")).toBe(tone);
    for (const cls of TONE_CLASSES[tone].split(" ")) expect(chip.className).toContain(cls);
    expect(chip.getAttribute("title")).toBe(`Task state: ${state}`);
  });

  it("uses distinct tones for success vs failure terminal states", () => {
    expect(TASK_STATE_TONES.COMPLETED).toBe("success");
    expect(TASK_STATE_TONES.FAILED).toBe("danger");
    expect(TASK_STATE_TONES.DEAD_LETTERED).toBe("danger");
    expect([...TERMINAL_TASK_STATES].every((s) => s in TASK_STATE_TONES)).toBe(true);
  });

  it("falls back to a neutral chip for an unknown future state", () => {
    render(<TaskStateChip state="SOMETHING_NEW" />);
    expect(screen.getByText("Something new").getAttribute("data-tone")).toBe("neutral");
  });
});
