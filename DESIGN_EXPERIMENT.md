# DESIGN_EXPERIMENT: New Dashboard Design

## Goal
Create an alternative dashboard design for HoYo Code Monitor inspired by modern dark-mode admin dashboards (Linear, Overmind, Tracebit) while keeping the existing HTMX + vanilla CSS architecture.

## Inspiration Sources

### Linear (linear.app)
- **Palette**: Deep charcoal base, warm gold accent (#b69a24), monochrome neutrals
- **Typography**: Inter Variable, tight tracking on headings (-1.4px), generous whitespace
- **Layout**: Expansive negative space, centered content, 1440px max container
- **Vibe**: Minimalist, precision, developer-tool aesthetic

### Overmind (overmindlab.ai)
- **Palette**: Cold obsidian base, sharp amber accent (#ec6d1c), pixelated glyphs
- **Typography**: mondwest display, neueBit body, GeistPixelSquare captions
- **Layout**: Terminal/CRT aesthetic, retro-futurist
- **Vibe**: Cold, technical, high-contrast

### Tracebit (tracebit.com)
- **Palette**: Pale limestone base, burnt orange accent (#e14b1e), Swiss precision
- **Typography**: TWK Lausanne Pan, clinical Swiss precision
- **Layout**: Clinical Swiss, generous whitespace, high-contrast
- **Vibe**: Clinical, precise, developer-tool

## Design Decisions for HoYo Code Monitor

### Palette (Dark Mode First)
```
--bg-deep:       #0a0c10      /* Deep charcoal, near-black */
--bg-card:       #111418      /* Card background */
--bg-elevated:   #181c22      /* Elevated surfaces */
--border:        #1f2428      /* Subtle borders */
--border-strong: #2a2f36      /* Stronger borders */

--fg-primary:    #e8e8e8      /* Primary text */
--fg-secondary:  #9ca3af      /* Secondary text */
--fg-muted:      #6b7280      /* Muted text */

--accent-gold:   #c9a832      /* Primary accent (HoYo gold) */
--accent-gold-dim: #a08528    /* Dimmed gold */
--accent-teal:   #2dd4bf      /* Secondary accent (teal) */
--accent-amber:  #f59e0b      /* Warning/amber */

--good:          #22c55e      /* Success */
--good-bg:       #052e16      /* Success background */
--bad:           #ef4444      /* Error */
--bad-bg:        #2e0a0a      /* Error background */
```

### Typography
- **Display**: Inter Variable (or system-ui fallback), tight tracking
- **Body**: Inter Variable / system-ui, 14px base, 1.5 line-height
- **Mono**: JetBrains Mono / Consolas / monospace for codes/numbers
- **Tracking**: -0.02em on headings, 0 on body

### Layout
- **Container**: 1280px max, centered
- **Spacing scale**: 4px base unit (4, 8, 12, 16, 24, 32, 48, 64)
- **Border radius**: 8px cards, 6px buttons, 4px inputs
- **Shadows**: Subtle, layered (0 1px 3px rgba(0,0,0,0.3), 0 4px 12px rgba(0,0,0,0.2))

### Components

#### Dashboard Layout
```
┌─────────────────────────────────────────────────────────────┐
│  Header: Logo | Game tabs | Search | Theme | User          │
├─────────────────────────────────────────────────────────────┤
│  Stats bar: Total | Redeemed | Pending | Failed | Rate     │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────┐  ┌─────────────────────────┐  │
│  │ Recent Codes Table      │  │ Quick Actions           │  │
│  │ (sortable, filterable)  │  │ [Add Account] [Scan]    │  │
│  │                         │  │ [Run Once] [Settings]   │  │
│  └─────────────────────────┘  └─────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  Sources panel (collapsible) | Redemption Log (collapsible) │
└─────────────────────────────────────────────────────────────┘
```

#### Table Design
- Sticky header with sort indicators
- Zebra striping (subtle, 6% opacity)
- Hover highlight (2% white overlay)
- Tabular numbers for codes/counts
- Status badges with semantic colors
- Row actions on hover (redeem, copy, delete)

#### Game Tabs
- 5 tabs: Genshin, HSR, ZZZ, HI3, ToT
- Each with distinct accent color
- Active tab: bottom border in game color
- Badge count for pending codes per game

#### Status Badges
- **Done**: Green bg + green text
- **Pending**: Amber bg + amber text
- **Expired**: Red bg + red text
- **Failed**: Red bg + red text
- **Invalid**: Gray bg + gray text

### Light Mode (Future)
- Invert bg/fg, keep same accent hues
- Increase contrast ratios to WCAG AA

## Implementation Plan

### Files to Create/Modify
1. `templates/dashboard_experiment.html` - New dashboard template
2. `static/css/experiment.css` - New stylesheet
3. `src/web_ui.py` - Add `/dashboard/experiment` route
4. `templates/base_experiment.html` - Extended base template

### CSS Architecture
- CSS custom properties for theming
- No Tailwind/utility classes (vanilla CSS)
- Mobile-first responsive (breakpoint: 768px)
- Reduced motion support
- High contrast mode support

### HTMX Integration
- Table sorting/filtering via HTMX
- Infinite scroll or pagination for codes
- Real-time updates via SSE for redemption status
- Toast notifications via HTMX events

## Acceptance Criteria
- [ ] Dashboard loads in <200ms
- [ ] Table sortable by all columns
- [ ] Filter by game, status, source
- [ ] Responsive down to 375px
- [ ] Dark/light theme toggle persists
- [ ] Accessible (WCAG AA contrast, keyboard nav)
- [ ] No layout shift on load
- [ ] Works in installed build (frozen exe)

## Risks
- HTMX + vanilla CSS may limit complex interactions
- Frozen exe size increase from new CSS
- Theme persistence across restarts
- Browser compatibility (Chromium in Playwright)