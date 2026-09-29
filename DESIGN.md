# Bibliotecario visual system

## Direction

A luminous reading room made of restrained liquid glass. The original ivory, deep teal, and brass palette gives the chrome its depth while keeping text clear. Book covers and PDF pages remain visually solid. The experience is calm enough for long reading sessions while buttons, search, and navigation feel precise and responsive.

## Materials and hierarchy

1. The page is a quiet atmospheric field with static ivory, sage, and brass light. It never animates behind the reader.
2. Navigation, the home hero, search, and small floating controls use frosted glass with one specular edge, moderate blur, and soft reflected light.
3. Catalogue cards and book mats are mostly opaque with soft inset and offset shadows. Their content does not depend on transparency for contrast.
4. PDF pages stay plain white and untouched by blur, transforms, or surface effects. Only the reader chrome receives the visual system.

The shared `--lg-*` properties in `static/css/liquid.css` are the source of truth for the light and dark palettes. Route-specific liquid stylesheets use those tokens.

## Type and composition

The existing self-hosted DM Sans family carries headings, body text, and controls. Large headings use compact line spacing and balanced wrapping. DM Serif Display is reserved for any book artwork that benefits from an editorial accent, not for interface headings. Layouts provide generous margins around focused tasks and tighter spacing within controls.

## Interaction

The first visit reveals the Bibliotecario mark through a glass lens, then fades to the site. `localStorage` records the visit at the start, so reloads and later pages skip it. Reduced-motion users see the site immediately. Hover and press feedback is small and limited to appropriate input types; page scrolling and PDF gestures are never animated by the shell.

## Adaptation

The catalogue moves from three columns to two and then one where cover size requires it. The navigation stays visible on mobile, including the staff Panel link. The reader retains its existing toolbar and PDF viewport height relationship at each breakpoint. Touch targets are at least 44 px where practical, phone inputs stay at 16 px, and safe-area padding protects floating controls.

## Boundaries

Keep all product copy, server routes, forms, book operations, search, downloads, dark mode, and reader behavior. Glass effects stay on a small number of chrome surfaces to avoid excessive stacked backdrop filters. Reduced transparency and increased contrast preferences receive more solid surfaces.
