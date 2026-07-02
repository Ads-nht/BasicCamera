---
name: High-Tech Workstation
colors:
  surface: '#0b1326'
  surface-dim: '#0b1326'
  surface-bright: '#31394d'
  surface-container-lowest: '#060e20'
  surface-container-low: '#131b2e'
  surface-container: '#171f33'
  surface-container-high: '#222a3d'
  surface-container-highest: '#2d3449'
  on-surface: '#dae2fd'
  on-surface-variant: '#bbcabf'
  inverse-surface: '#dae2fd'
  inverse-on-surface: '#283044'
  outline: '#86948a'
  outline-variant: '#3c4a42'
  surface-tint: '#4edea3'
  primary: '#4edea3'
  on-primary: '#003824'
  primary-container: '#10b981'
  on-primary-container: '#00422b'
  inverse-primary: '#006c49'
  secondary: '#b9c7e0'
  on-secondary: '#233144'
  secondary-container: '#3c4a5e'
  on-secondary-container: '#abb9d2'
  tertiary: '#ffb3ad'
  on-tertiary: '#68000a'
  tertiary-container: '#ff7a73'
  on-tertiary-container: '#79000e'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#6ffbbe'
  primary-fixed-dim: '#4edea3'
  on-primary-fixed: '#002113'
  on-primary-fixed-variant: '#005236'
  secondary-fixed: '#d5e3fd'
  secondary-fixed-dim: '#b9c7e0'
  on-secondary-fixed: '#0d1c2f'
  on-secondary-fixed-variant: '#3a485c'
  tertiary-fixed: '#ffdad7'
  tertiary-fixed-dim: '#ffb3ad'
  on-tertiary-fixed: '#410004'
  on-tertiary-fixed-variant: '#930013'
  background: '#0b1326'
  on-background: '#dae2fd'
  surface-variant: '#2d3449'
typography:
  display-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: '1.2'
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: '1.3'
  headline-sm:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '500'
    lineHeight: '1.4'
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.5'
  body-sm:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: '1.5'
  label-caps:
    fontFamily: Geist
    fontSize: 11px
    fontWeight: '600'
    lineHeight: '1'
    letterSpacing: 0.05em
  mono-data:
    fontFamily: Geist
    fontSize: 12px
    fontWeight: '400'
    lineHeight: '1'
    letterSpacing: 0em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  base: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 40px
  gutter: 16px
  sidebar-width: 260px
  bottom-nav-height: 64px
---

## Brand & Style
The design system is engineered for professional surveillance and camera management environments where reliability and clarity are paramount. The brand personality is technical, precise, and unobtrusive, positioning the software as a sophisticated tool rather than a consumer app. 

The aesthetic draws from **Minimalism** and **Corporate Modern** styles, utilizing a "Dark Workstation" theme to reduce eye strain during long monitoring sessions. High-density layouts, micro-borders, and a restrained use of vibrant accents create a high-performance environment that feels responsive and hardware-accelerated.

## Colors
The palette is built on a foundation of deep slate grays to provide maximum contrast for video feeds. 
- **Primary (#10b981):** Reserved strictly for "Active," "Online," and "Recording" states. It signifies system health and connectivity.
- **Secondary (#334155):** Used for structural micro-borders and inactive UI elements to maintain a low visual profile.
- **Tertiary (#ef4444):** Used for alerts, motion detection warnings, and critical system failures.
- **Neutrals:** The background utilizes `#0f172a` for the canvas, with `#1e293b` used for elevated surfaces like sidebars and card containers.

## Typography
The system uses **Inter** for its exceptional readability at small sizes and high-density information environments. **Geist** is introduced for labels and technical data (timestamps, IP addresses, bitrates) to provide a monospaced, developer-friendly precision.

Typography is optimized for a high-density "HUD" (Heads-Up Display) feel. Headlines are tight and bold, while body text remains legible against dark backgrounds. Labels utilize uppercase tracking to differentiate metadata from interactive content.

## Layout & Spacing
The layout follows a **Fluid Grid** model designed for multi-stream viewing. 

- **Desktop:** Features a fixed `260px` left-hand sidebar for device navigation and a flexible main stage for video grids. 
- **Mobile:** Transitions to a `64px` bottom navigation bar. Detailed controls and settings are handled via **Fluid Overlay Sheets** that slide up from the bottom, occupying 90% of the screen height to maintain context.
- **Spacing Rhythm:** Based on a 4px scale. Components use `16px` (md) for standard padding, while internal elements like icons and labels use `8px` (sm) to maintain a compact, professional density.

## Elevation & Depth
This design system avoids traditional drop shadows in favor of **Tonal Layers** and **Micro-borders**. 

- **Level 0 (Base):** `#0f172a` — The main application canvas.
- **Level 1 (Surfaces):** `#1e293b` — Used for sidebars and panels, separated from the base by a 1px solid border of `#334155`.
- **Level 2 (Popovers/Modals):** A slightly lighter slate with a very subtle, 10% opacity white inner-glow to simulate a bezel.
- **Glassmorphism:** Applied sparingly to overlay controls on top of video feeds. These use a 12px backdrop blur and a 20% transparent slate fill to ensure UI elements remain legible regardless of the video content beneath.

## Shapes
The shape language is "Soft-Industrial." A universal `0.25rem` (4px) corner radius is applied to buttons and inputs to feel modern but structured. Larger containers, such as video feed windows, use `0.5rem` (rounded-lg) to create a distinct visual frame. The focus is on sharp, clean lines that maximize the usable area for video content.

## Components

- **Buttons:** Primary buttons use the Accent Green background with black text for maximum "Online" visibility. Secondary buttons are "Ghost" style with `#334155` borders.
- **Skeleton Loading:** Bones utilize a linear gradient shimmer from `#1e293b` to `#334155`, animated over 1.5s to indicate hardware-accelerated processing.
- **Video Tiles:** The core component. Includes a top-right status chip (Live/Rec) and a bottom-overlay scrim for the camera name and timestamp.
- **Input Fields:** Dark-filled with no background, defined only by a bottom micro-border that illuminates in Accent Green on focus.
- **Sticky Navigation:** Desktop sidebar uses active-state vertical pips. Mobile bottom-tabs use haptic-ready icons with label-caps typography.
- **Status Chips:** Small, pill-shaped indicators. Green for "Connected," Red for "Motion Detected," and Slate for "Offline."