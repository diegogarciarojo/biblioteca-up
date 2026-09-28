# Biblioteca UP

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- Public readers browse, search, read, and download books in PDF format.
- Staff members manage the collection through a login and a dedicated panel.

These roles are inferred from the current routes and templates; the project does not state a narrower audience.

## Product Purpose

Provide an online library where readers can find a book and read it directly in the browser or download its original PDF. Staff can publish and maintain the collection.

## Operating Context

The public site includes a searchable, paginated catalogue, book detail pages, and an integrated PDF reader. The reader supports page navigation, zoom, selectable text, in-book search, and mobile pinch gestures. The staff panel supports upload, metadata editing, optional PDF replacement, and deletion.

## Capabilities and Constraints

- Keep all existing pages, copy, content, and features during the visual redesign.
- Preserve the reader's page geometry, scroll container, and DOM hooks used by its JavaScript.
- Support desktop and mobile use, keyboard focus, reduced motion, and the existing light/dark theme preference.
- The first-visit introduction appears once per browser storage state and is skipped on later visits and reloads.

## Brand Commitments

- Keep the name Biblioteca UP.
- The requested replacement visual language combines restrained glassmorphism and neumorphic depth with an Apple Liquid Glass influence.

## Evidence on Hand

The existing Django routes, templates, local PDF assets, stylesheets, and JavaScript provide the product content and interaction model. No external claims or new catalogue content are needed for this redesign.

## Product Principles

- Make finding and opening a book immediate.
- Keep book covers and PDF pages readable as the main content.
- Give staff actions clear feedback and unambiguous controls.
