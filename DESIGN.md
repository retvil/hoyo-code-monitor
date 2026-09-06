# DESIGN.md

## Genshin Code Monitor - UI Redesign

### Color Scheme (Genshin Dark Theme)
- Background: #0f172a (slate-900)
- Surface: #1e293b (slate-800)
- Primary Accent: #06b6d4 (neon cyan)
- Secondary Accent: #8b5cf6 (violet)
- Text: #e2e8f0 (slate-200)
- Muted Text: #64748b (slate-500)
- Success: #10b981 (emerald)
- Error: #ef4444 (red)
- Warning: #f59e0b (amber)

### Typography
- Display Font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif
- Code Font: 'JetBrains Mono', monospace
- Font Weights: 400 (regular), 600 (semi-bold), 700 (bold)

### Border Radius
- Default: 0.5rem (rounded)
- Large: 1rem (rounded-2xl)

### Effects
- Glassmorphism: background: rgba(30, 41, 59, 0.5); backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.1);
- Shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
- Transition: all 0.2s ease-in-out

### Layout
- Container: max-width: 7xl (1440px); margin: 0 auto; padding: 1.5rem;
- Grid Gap: 1.5rem
- Card Padding: 1.5rem

### Components
- Button: 
  - Primary: bg-[#06b6d4] text-white hover:bg-[#0891b2] 
  - Secondary: bg-[#1e293b] text-[#e2e8f0] hover:bg-[#334155]
  - Success: bg-[#10b981] text-white hover:bg-[#059669]
  - Error: bg-[#ef4444] text-white hover:bg-[#dc2626]
  - Ghost: bg-transparent text-[#06b6d4] hover:bg-[#06b6d4/10]
- Input: 
  - bg-[#1e293b] text-[#e2e8f0] border border-[#334155] focus:border-[#06b6d4] focus:ring-2 focus:ring-[#06b6d4/20]
- Badge: 
  - px-2 py-1 rounded-full text-xs font-medium
  - bg-[#06b6d4/10] text-[#06b6d4]
  - Success: bg-[#10b981/10] text-[#10b981]
  - Error: bg-[#ef4444/10] text-[#ef4444]
  - Warning: bg-[#f59e0b/10] text-[#f59e0b]
- Table: 
  - bg-[#1e293b] border border-[#334155]
  - hover:bg-[#334155]
  - th: bg-[#0f172a] text-[#e2e8f0] font-medium
  - td: text-[#e2e8f0]
- Stat Card: 
  - bg-[#1e293b] border border-[#334155] rounded-lg
  - hover:bg-[#334155]
  - value: text-3xl font-bold text-[#e2e8f0]
  - label: text-sm font-medium text-[#64748b]
- Empty State: 
  - text-center py-12
  - text-[#64748b]
  - svg: h-12 w-12 text-[#64748b]/50

### HTMX Attributes to Preserve
All hx-get, hx-post, hx-trigger, hx-target, hx-swap, hx-indicator, hx-confirm, hx-on::after-request must remain unchanged.

### Jinja Variables to Preserve
All {{ variable }} and {% block %} ... {% endblock %} must remain unchanged.

### Implementation Notes
- Replace all existing CSS with Tailwind CSS via CDN: https://cdn.tailwindcss.com
- Use CSS variables for colors defined above
- Maintain the same HTML structure and Jinja blocks
- Only change class names and add Tailwind classes
- Keep all existing functionality intact