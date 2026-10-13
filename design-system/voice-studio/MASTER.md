# Design System Master File

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** 小宣 Voice Studio
**Generated:** 2026-10-13 01:00:02
**Category:** Text-to-speech productivity studio
**Design Dials:** Variance 4/10 (Balanced / Modern) | Motion 3/10 (Subtle) | Density 6/10 (Standard)

---

## Global Rules

### Color Palette

| Role | Hex | CSS Variable |
|------|-----|--------------|
| Primary | `#4F46E5` | `--color-primary` |
| On Primary | `#FFFFFF` | `--color-on-primary` |
| Secondary | `#6D5DFB` | `--color-secondary` |
| Accent/CTA | `#4F46E5` | `--color-accent` |
| Background | `#F4F5FA` | `--color-background` |
| Surface | `#FFFFFF` | `--color-surface` |
| Foreground | `#111827` | `--color-foreground` |
| Muted | `#64748B` | `--color-muted` |
| Border | `#E2E6F0` | `--color-border` |
| Success | `#0F8A5F` | `--color-success` |
| Destructive | `#DC2626` | `--color-destructive` |
| Ring | `#4F46E5` | `--color-ring` |

**Color Notes:** Mist-gray canvas, white surfaces, indigo-to-violet primary action, restrained emerald success.

### Typography

- **Heading Font:** Inter / PingFang SC / Microsoft YaHei / system-ui
- **Body Font:** Inter / PingFang SC / Microsoft YaHei / system-ui
- **Mood:** minimal, precise, premium, calm, productive
- **Loading:** Use the system stack first; do not make the interface depend on a remote font request.

**CSS Import:**
```css
font-family: Inter, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
```

### Spacing Variables

*Density: 6/10 — Standard*

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `4px` / `0.25rem` | Tight gaps |
| `--space-sm` | `8px` / `0.5rem` | Icon gaps, inline spacing |
| `--space-md` | `16px` / `1rem` | Standard padding |
| `--space-lg` | `24px` / `1.5rem` | Section padding |
| `--space-xl` | `32px` / `2rem` | Large gaps |
| `--space-2xl` | `48px` / `3rem` | Section margins |
| `--space-3xl` | `64px` / `4rem` | Hero padding |

### Shadow Depths

| Level | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | Subtle lift |
| `--shadow-md` | `0 12px 32px rgba(51,65,85,0.08)` | Cards, buttons |
| `--shadow-lg` | `0 20px 54px rgba(51,65,85,0.11)` | Main workbench, dropdowns |
| `--shadow-xl` | `0 28px 80px rgba(51,65,85,0.14)` | Modals only |

---

## Component Specs

### Buttons

```css
/* Primary Button */
.btn-primary {
  background: linear-gradient(110deg, #3B82F6 0%, #5B4FF0 100%);
  color: white;
  padding: 12px 24px;
  border-radius: 12px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}

.btn-primary:hover {
  opacity: 0.9;
  box-shadow: 0 10px 24px rgba(79, 70, 229, 0.20);
}

/* Secondary Button */
.btn-secondary {
  background: transparent;
  color: #334155;
  border: 1px solid #D8DEE9;
  padding: 12px 24px;
  border-radius: 10px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}
```

### Cards

```css
.card {
  background: #FFFFFF;
  border: 1px solid #E2E6F0;
  border-radius: 16px;
  padding: 24px;
  box-shadow: var(--shadow-md);
  transition: all 200ms ease;
  cursor: default;
}

.card:hover {
  box-shadow: var(--shadow-lg);
  border-color: #CDD4E2;
}
```

### Inputs

```css
.input {
  padding: 12px 16px;
  border: 1px solid #E2E8F0;
  border-radius: 8px;
  font-size: 16px;
  transition: border-color 200ms ease;
}

.input:focus {
  border-color: #4F46E5;
  outline: none;
  box-shadow: 0 0 0 3px #4F46E51F;
}
```

### Modals

```css
.modal-overlay {
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
}

.modal {
  background: white;
  border-radius: 16px;
  padding: 32px;
  box-shadow: var(--shadow-xl);
  max-width: 500px;
  width: 90%;
}
```

---

## Style Guidelines

**Style:** Minimal premium productivity workbench

**Keywords:** minimal, premium, indigo, lavender mist, polished, calm, dense-but-clear, editorial workspace

**Best For:** Browser-based creation tools with a large editor and a searchable asset catalog

**Key Effects:** Indigo→violet primary CTA, restrained selected states, long soft shadows, hairline borders, generous outer whitespace, no decorative motion.

### Page Pattern

**Pattern Name:** Two-column creation workbench

- **Conversion Strategy:** Let users choose a voice and edit text without leaving the page; keep one visually dominant generation action.
- **CTA Placement:** Full-width at the bottom of the editing flow, sticky only when it does not cover content.
- **Desktop Layout:** Compact searchable voice catalog on the left; wide editor, parameters and result on the right.
- **Mobile Layout:** Text first, then voice picker, parameters, generate action and output.

---

## Motion

**State transition** (Subtle) — Trigger: selection, loading and completion | Duration: 180-240ms | Easing: `cubic-bezier(.2,.8,.2,1)`

```js
transition: color 200ms ease, background-color 200ms ease, border-color 200ms ease, box-shadow 200ms ease, opacity 200ms ease;
```

**Framework notes:** Use CSS only; the product does not need GSAP.

- ✅ Animate only state feedback and preserve spatial continuity.
- ❌ Do not animate width, height, list reflow or essential content visibility.
- ⚡ Disable nonessential transitions under `prefers-reduced-motion`.

---

## Anti-Patterns (Do NOT Use)

- ❌ Excessive pills, badges, borders or nested toolbars
- ❌ Low-density landing-page whitespace inside the working area
- ❌ Multiple gradient buttons competing for attention

### Additional Forbidden Patterns

- ❌ **Emojis as icons** — Use SVG icons (Heroicons, Lucide, Simple Icons)
- ❌ **Missing cursor:pointer** — All clickable elements must have cursor:pointer
- ❌ **Layout-shifting hovers** — Avoid scale transforms that shift layout
- ❌ **Low contrast text** — Maintain 4.5:1 minimum contrast ratio
- ❌ **Instant state changes** — Always use transitions (150-300ms)
- ❌ **Invisible focus states** — Focus states must be visible for a11y

---

## Pre-Delivery Checklist

Before delivering any UI code, verify:

- [ ] No emojis used as icons (use SVG instead)
- [ ] All icons from consistent icon set (Heroicons/Lucide)
- [ ] `cursor-pointer` on all clickable elements
- [ ] Hover states with smooth transitions (150-300ms)
- [ ] Light mode: text contrast 4.5:1 minimum
- [ ] Focus states visible for keyboard navigation
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive: 375px, 768px, 1024px, 1440px
- [ ] No content hidden behind fixed navbars
- [ ] No horizontal scroll on mobile
