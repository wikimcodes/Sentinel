# Summary

Sentinel is a patient dashboard for clinical teams, built in the "Coral and Ink" editorial system: a bold coral primary color against a deep ink-blue foundation for a modern, calm, editorial aesthetic. It relies on large-scale serif typography, generous white space, and smooth, non-linear animations (cubic-bezier) to convey clinical clarity and premium, trustworthy craftsmanship.

# Style

The style is defined by its high-contrast color duo: Coral (#EF4623) and Ink (#2D3B42). Typography follows an editorial hierarchy: 'Instrument Serif' for expressive, large-scale headlines (italicized for emphasis) and 'Manrope' (weights 300–700) for functional UI elements and body copy. UI elements use large corner radii (rounded-3xl to rounded-[3rem]) and subtle depth through 'Soft Peach' (#FDF1EE) background accents and soft blurs.

## Spec

Apply a 'Coral and Ink' editorial style. Primary color: #EF4623 (Coral); Secondary color: #2D3B42 (Ink); Background Accent: #FDF1EE (Soft Peach). Typography: Use 'Instrument Serif' for headings (sizes 60px to 160px, tracking-tight) and 'Manrope' for body (18px, leading-relaxed). For animations, use a custom cubic-bezier(0.16, 1, 0.3, 1) curve for 'fade-up' effects that include a starting 2-degree rotation. Navigation must be a glassmorphism header (backdrop-blur 12px, white/80 opacity). Buttons should have a 30px corner radius and include a shadow-lg shadow-primary/20. Use ambient background blurs (#EF4623 at 10% opacity) with 100px–120px blur radii to create depth.

# Layout & Structure

An asymmetrical, modular structure using a mix of full-width hero sections and bento-grid feature areas. Content is revealed via scroll-triggered transitions. Copy speaks to clinicians and clinic staff — plain, calm, and specific to the clinical day (vitals, appointments, medications, care plans, alerts). Avoid marketing jargon; name things by what the care team controls and recognizes.

## Navigation

Fixed top navigation. Left: Logo mark (square #EF4623 container with 3-degree rotation) followed by the wordmark "Sentinel" in Instrument Serif. Center/Right: Text links in Manrope (text-sm, font-semibold, #2D3B42 80% opacity) — Overview, Features, Care teams, Security. Right CTA: Pill-shaped button (#EF4623, white text, uppercase text-xs) labeled "Request access". On scroll, apply a background: rgba(255, 255, 255, 0.8) with 12px backdrop-blur and a subtle bottom border.

## Hero Section

Centered layout with high-impact serif typography. Top element: Small pill badge with #FDF1EE background and a 'pulse/activity' icon, reading "Built for clinical teams". Heading: Two-line layout using Instrument Serif at 10rem (mobile 4rem) — first line "Every patient," second line italicized and colored #EF4623 "in full view." Subtext: Max-width 2xl, Manrope text-lg, #2D3B42/70 — explain that Sentinel brings vitals, appointments, medications, and care plans into one calm workspace. CTAs: Primary pill button "Request a demo" with shadow-2xl; Secondary ghost button "Watch the tour" with 2px border-ink/10. Background: Large ambient blur circles at top-right and bottom-left.

## Value Proposition (Bento)

Two-column grid. Left: Text-heavy with large Serif H2 ("A calmer command center for care.") and a vertical feature list using 56px rounded-2xl icon containers — "Live vitals, always current", "One record, everyone aligned", "Alerts that reach the right nurse". Right: A 'Patient Dashboard Simulator' component — a dark-themed browser window (#2D3B42) containing a simplified white patient-record interface: a patient header with avatar and a "Stable" status pill, a two-column vitals grid (one peach Heart Rate block, one grey Blood Pressure block), abstract skeleton loaders, and a glassmorphism status bar at the bottom reading "Vitals synced".

## Features Grid

Three-column bento grid. Cards use 3rem (48px) border radius. Card Style 1 (Large): Spans 2 columns, white background, #2D3B42 border/5, features a large background 'pulse' icon at 5% opacity — "Live vitals, monitored around the clock". Card Style 2 (Dark): Solid #2D3B42 background, white text, #EF4623 accent icons — "Alerts, routed to the right hands". Card Style 3 (Standard): White background, vertical layout, accent icon shifts color on hover — "Appointments at a glance", "Medication tracking", "Care team, in sync".

## Call to Action

Full-width section with a 4rem (64px) rounded container in solid #EF4623. Background pattern: subtle white dot grid (opacity 20%, 30px spacing). Heading: Serif text at 8rem — "Ready when your clinic is." (second phrase italicized). Buttons: High-contrast white background button with #EF4623 text labeled "Request a demo". Include a trust-bar footer with small uppercase tracking-widest text — "HIPAA-ready · SOC 2 Type II · Trusted by 200+ clinics".

## Footer

Deep Ink (#2D3B42) background. 5-column grid. Column 1: "Sentinel" logo and social icons in circular white/10 borders, plus a one-line descriptor ("The patient dashboard clinical teams keep open all shift."). Columns 2–4: Product / Resources / Company links with H4 serif headers (Product: Vitals monitoring, Appointments, Medications, Care teams). Bottom bar: 1px top border (white/5), horizontal list of legal links (Privacy, Terms, HIPAA), copyright text.

# Special Components

## Animated Patient Dashboard Simulator

A floating mockup window representing the Sentinel patient interface.

Create a card with #2D3B42 background and 40px radius. Inside, place a white container with rounded-3xl corners. Top bar: 3 colored 'window' dots and a skeleton address bar. Content: 3 vertical sections — a patient header row (avatar skeleton, name skeleton, "Stable" status pill), a 2-column vitals grid with one peach block (Heart Rate, e.g. "72 bpm" in serif coral) and one grey block (Blood Pressure, e.g. "118/76"), and a bottom skeleton text block. Footer: A glassmorphism blur bar with a green check-circle icon reading "Vitals synced" and two clinical mono chips (dark rounded rectangles, e.g. "SpO₂ 98%" and "Temp 36.8°").

## Clinical Reasoning Panel (Explainability)

A panel that appears whenever Sentinel surfaces a recommendation or suppresses an alert, explaining the "why" in plain language so the care team can verify the decision.

Create a card with white background, rounded-3xl corners, and a 4px left accent border in #EF4623. Header: a small uppercase label in Manrope (text-xs, tracking-widest, #2D3B42/50) — "Why this was recommended" or "Why this alert was suppressed" — paired with a small 'shield-check' or 'info' icon. Body: a plain-language explanation in Manrope (text-base, leading-relaxed) that states the suppression logic or recommendation rationale.

Referenced guidelines appear as inline hyperlinks (see functional spec for linking behavior). Link styling: color #EF4623, font-medium, a subtle underline (underline-offset-2, decoration-#EF4623/40), and a small trailing external-link icon; on hover, deepen the underline to full opacity. Footer: a muted timestamp and rule-version label in Manrope text-xs, #2D3B42/50.

## The 'Rotating Logo' Brand Mark

A simple but dynamic logo mark.

A 36px square container using #EF4623. Apply a 3-degree rotation by default. Inside, place a single white uppercase letter "S" in Instrument Serif, Bold, Italic. On hover, the container should rotate to 12 degrees with a 300ms transition.

# Special Notes

MUST: Use 'Instrument Serif' specifically for emphasis and large headers to maintain the editorial feel. MUST: Use the cubic-bezier(0.16, 1, 0.3, 1) curve for all entry animations. MUST: Use large corner radii (min 24px) for all containers. MUST: Keep clinical copy calm, plain, and specific — vitals, appointments, medications, care plans, alerts. MUST: Style guideline references as coral (#EF4623) hyperlinks with a subtle underline and a trailing external-link icon (linking behavior and data requirements live in the functional spec, not here). DO NOT: Use standard blue or green for primary actions; stick strictly to #EF4623 (a green check-circle is permitted only as the "synced" status indicator). DO NOT: Use sharp 90-degree corners on any primary UI containers. DO NOT: Overstate medical claims or imply diagnostic capability.
