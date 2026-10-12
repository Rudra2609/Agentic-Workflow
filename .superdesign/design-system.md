# HMAP design system

## Product context
HMAP (hierarchical multi-agent platform) turns a goal into finished work. A person types a goal (or uploads a
requirements document); a Manager agent extracts requirements and makes a plan; the person reviews/approves the plan
(or runs automatically); specialist agents (Analyst, Planner, Researcher, Fact-checker, Developer, Tester, Writer,
Reviewer) do the steps; results and files stay in the person's private workspace. Every project has runs (history is
kept) and a red Stop control that always works.

Audiences: (1) non-technical people who want AI to do a task — must understand everything in plain words;
(2) developers who toggle Developer mode to see ids, raw events, agent registry.

Jobs to be done: describe a goal; check what the AI understood and its plan; approve or stop; watch progress;
understand problems; get results; return later.

## Key pages
- `/` Workspace: greeting, honest "test environment" notice (agents are placeholders), goal composer ("What would you
  like your AI team to do?", describe/upload, mode: Review the plan first / Run automatically, Create project),
  project list with search and filters (All, In progress, Needs attention, Completed, Stopped, Archived).
- `/projects/[id]`: pipeline stages (Request, Understanding, Plan, Review, Work), plan review/approval, requirements,
  plan dependency graph, step inspector, results & files, run history, activity.
- `/team` AI team roles (+ registry in developer mode), `/activity` timeline, `/issues`, `/settings`, sign-in pages.
- App shell: left sidebar (logo, Workspace: My projects [count], AI team, Activity, Issues; Tools: Echo; server/live
  status; user menu with theme + Developer mode + Settings + Sign out); mobile top bar.

## Current tokens (for faithful reproduction)
Light: canvas #e8ece5, sidebar #dde3d9, surface #f5f7f2, surface-2 #e0e6dc, fg #1c2620, fg-2 #3f4d45, muted #66736b,
line #ccd4c8, line-strong #b2bdae, accent #f0b23a (saffron fill, text on it #1c2620), accent-ink #7d5300 (links),
focus/info #2f7a68 (jade), success #2c6e45, warning #a34a14 (rust), danger #a32d24 (brick).
Dark: canvas #111814, surface #17201b, fg #e6ece4, muted #829087, line #25322b, accent #f2b33d.
Type: Bricolage Grotesque (headings), Hanken Grotesk (body), JetBrains Mono (ids only).
Buttons are tactile keycaps (2px darker bottom edge, press down on click); floating panels have soft deep shadows.

## Redesign brief — NEW visual style (hard constraints for every variation)
- Create a NEW, distinctive visual language. Do not reuse the pine/saffron palette above in variations.
- NO purple, NO blue, NO violet/indigo, NO purple-blue gradients, NO neon. No warm-cream + terracotta default, no
  black + acid-green default.
- Avoid the "rounded card everywhere" SaaS kit: content should not be chopped into identical boxed cards; use
  typography, space, rules, and a few deliberately lifted surfaces.
- The person wants things with a 3D / physical feeling that people enjoy: depth, layered planes, tactile controls,
  perspective, soft real shadows, materials (e.g. glass, paper, clay, metal) — used with intent, not everywhere.
- No all-caps labels, no "A · B · C" metadata strings, no gradient-accented single headline word, no "→" glued to
  every button.
- Plain-language copy; status never by colour alone (dot/shape + words).
- Must work in light and dark themes and down to mobile; visible keyboard focus.
- Keep the real content, page structure and features (composer, mode choice, filters, search, project rows with
  status and last activity, placeholder notice, sidebar items and counts).
- Logo: the HMAP mark (three stacked plates) must stay.

## Chosen direction (implemented): "Paper workshop"
Light: sage-green desk #9cc492 with paper grain, white sheets #ffffff, ink #1c2420, muted #5e6b63, lines #d3ddd1,
malachite actions #1f7a5a (edge #165c43, text white), amber review #a8661a, brick errors #b23a2b, sticky note #fbefa6.
Dark ("darkroom safelight"): desk #140c0b, paper #1f1514 / #281c1a, ink #f2e4d8, muted #a39185, lines #3a2826,
safelight-red actions #e5533d (edge #9e3324, text #140c0b), fixer-green done #8fbf8a, amber review #e3a64e,
danger #ff8f78 as OUTLINED keys (red is the action colour), sticky #3a2a1c / #f1d9b5.
Type: Archivo only (headings at width 112, weight 700). Materials: binder spine + index-tab nav, the page as a sheet on
the desk, sticky-note notices, paper-clipped sheets with perforated footers, slips in a tray, stamped-tab buttons,
the 3D hierarchy stack on sign-in.
Per page: Workspace = sticky note + clipped composer + project slips in a tray; Project = stamped stage keys + clipped
plan review; AI team = sticky note + role slips with rubber "Placeholder" stamps; Activity = a logbook, one folder tab
per day, times in a ruled (double red) margin, repeated lines collapsed with a count; Issues = clipped failure sheets
with a perforated action strip + "Returned" stamped slips; Settings = four clipped sheets, form actions on the
perforated strip; Echo = agent slips in a tray. Disabled primary keys are pressed flat (dashed outline, no fill).
