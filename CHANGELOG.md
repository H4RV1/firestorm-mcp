# Local builder development (0.3.0a3+builder.1)

- Reuse the upstream LEAP bridge and add ten builder tools, including explicit
  capability reporting, registered external-script read/write and live latency.
- Add opt-in session ExternalEditor integration, UTF-8 writes with expected
  hashes, exact backups, viewer/file identity checks and control-lease checks.
- Compile the native selection/linkset/face API in a separate viewer. Startup,
  discovery, empty selection and missing-object errors passed live MCP checks;
  in-world link/face accuracy is still unverified. Stock viewers remain unsupported.
- Isolate the development installation and settings profile; record the pinned
  build baseline and provide portable staging and release-update instructions.
- Handle Windows Python venv redirectors when resolving the owning viewer.
- Add read-only Build-panel summaries and executable fingerprints.
- Document source research, alternative MCP projects and outstanding native
  script lifecycle/compile-result work. No live script save has been tested.

# Changelog

## 0.3.0a3 — public alpha (12 September 2026)

- Shorten setup, capability, agent and contributor guides; add a brief AI-authorship note.
- Clarify tool descriptions without changing arguments or behavior.
- Publish the mesh-preview skill 0.1.1 with shorter instructions and explicit platform handling.
- Retain the existing platform and live-test limits. No consumer runtime is upgraded automatically.


## 0.3.0a2 — portable setup alpha (12 September 2026)

- Use one Python installer from Windows/POSIX wrappers, with a local virtual environment and generated absolute-path stdio configuration.
- Add offline setup diagnostics, conventional viewer discovery and explicit selection for ambiguous/nonstandard installations.
- Add experimental Linux distribution-wrapper and macOS app-bundle launch layouts; derive matching UI resource paths and platform-native state directories.
- Report native picker availability in connection status and reject unsupported file-selection calls before acquiring a viewer lease. Native picker automation remains Windows-only.
- Create POSIX session-token files with owner-only permissions from the first write.
- Expand CI to Linux x64/ARM64 and macOS Intel/ARM64, exercising source ZIP installation and a fresh wheel without a live viewer.
- Keep existing consumer installations untouched. New Linux/macOS/Pi live workflows remain unverified; the optional skill retains its Windows 0.3.0a1 live baseline.

## Mesh-preview skill 0.1.0 — optional companion (12 September 2026)

- Add a portable Agent Skills entrypoint and importer reference for the existing MCP 0.3.0a1.
- Package scoped discovery, source commits, checkbox keys, LOD captures, quote readback and cleanup as reusable instructions.
- Provide a separate skill ZIP with MIT licence/checksum and include the sources in future source distributions.
- Keep runtime APIs, the existing MCP release assets and active viewer installations unchanged.

## 0.3.0a1 — private compatibility baseline (11 September 2026)

- Migrate to official MCP Python SDK v2 while retaining legacy-client protocol support.
- Initialize/discover without contacting the viewer; discover live APIs explicitly through `capabilities_refresh`.
- Add `--tool-profile compact` to keep discovery at 43 workflow tools while retaining generic API access.
- Advertise and deliver catalog changes to legacy clients and modern subscription listeners, with deterministic ordering and private zero-TTL cache hints.
- Return structured results alongside existing JSON text/images; reject invalid/extra arguments before dispatch and report unknown tools as protocol errors.
- Add wire-level checks across five protocol revisions, host-specific setup guidance and a cited compatibility audit.
- Update pip inside the dedicated installation environment before resolving project packages; add a pinned independent Inspector check to CI.
- Add basename/exact/prefix/glob UI searches, depth limits and explicit pagination/truncation.
- Add `ui_click` registered-floater callbacks with unique-path validation and optional before/after observation.
- Require a visible enabled target `path` in `ui_press_key` (breaking safety change); target both key events and return selected-value readback. Selection by value also returns readback where supported.
- Flag black, nearly uniform and transparent captures without treating nonblank images as semantic verification.
- Refuse loopback HTTP redirects so bridge credentials/actions cannot follow a redirected endpoint.
- Drain bounded rejected HTTP bodies to avoid Windows connection resets; extend Windows CI to Python 3.14 and add dependency advisory checks.
- Preserve UI search pages when individual returned paths cannot be inspected.
- Add `mesh_preview_camera` for bounded path-targeted uploader zoom/pan/orbit; the current workflow catalog has 43 tools.
- Document the live importer workflow's separate selection/commit steps and the need to read the preview LOD again after file imports.

## 0.2.0a1 — private collaboration alpha

- Package the general-purpose bridge for source and wheel installation.
- Store runtime/captures outside the checkout using machine-local state with explicit overrides.
- Include a guarded Windows launcher and real stdio connection probe as installed commands.
- Publish a full capability map, tool schemas, agent guide and contributor workflow.
- Exclude private session reports, personal paths, product content and runtime data.
- Retain 42 workflow tools and historical reference for 94 discovered viewer operations.

The refactored launcher and expanded importer readback require live validation for this release. Prior integration evidence is described separately in docs/VALIDATION.md.
