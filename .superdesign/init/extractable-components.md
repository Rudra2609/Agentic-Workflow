# Extractable components

## AppShell
- Source: `frontend/src/components/AppShell.tsx`
- Category: layout
- Description: Sidebar (hmap mark, Workspace nav with counts, Tools nav, system status, user menu); mobile top bar + menu
- Extractable props: activeItem (string: "projects"|"team"|"activity"|"issues", default "projects"), needsAttentionCount (number, default 0), openIssuesCount (number, default 0), userName (string), userEmail (string)
- Hardcoded: nav labels, HmapMark SVG, status lines, all CSS

## AuthLayout
- Source: `frontend/src/app/(auth)/layout.tsx` + `frontend/src/components/AuthBackdrop.tsx`
- Category: layout
- Description: Sign-in split screen with the 3D hierarchy stack hero and lifted form card
- Extractable props: none
- Hardcoded: headline, copy, plates, CSS

## Button
- Source: `frontend/src/components/ui.tsx`
- Category: basic
- Description: Tactile keycap button (primary saffron, secondary, danger, ghost, quiet-danger)
- Extractable props: variant (string, default "secondary"), size ("sm"|"md")
- Hardcoded: keycap shadows

## StageRail
- Source: `frontend/src/components/Workflow.tsx`
- Category: basic
- Description: Five pipeline stages (Request, Understanding, Plan, Review, Work) as keycap markers joined by rails
- Extractable props: activeStage (string, default "review")
- Hardcoded: stage names, icons

## Status
- Source: `frontend/src/components/ui.tsx`
- Category: basic
- Description: Dot + label status (never colour alone)
- Extractable props: tone (string), label (string)
- Hardcoded: tone colours

## Field / Input
- Source: `frontend/src/components/ui.tsx`
- Category: basic
- Description: Label + input + hint/error wiring
- Extractable props: label, hint, error
- Hardcoded: input styles
