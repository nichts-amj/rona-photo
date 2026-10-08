# AI Retouch service

The frontend talks only to RetouchService (`web/retouch/ai-service.mjs`). Backend `service.py` owns documents, revisions, face caches and serial jobs. `models.py` provides FaceDetector, FaceParser, FaceRestorer and a separate ModelManager. `processors.py` provides independent SkinProcessor and BlemishProcessor plus protected masks and delta blending. The old Upscale lifecycle is untouched; only generic compatibility/import helpers and weight files are reused read-only.

## Models and runtime

`config.json` selects RetinaFace ResNet50 detection, ParseNet 19-class parsing and CodeFormer restoration. The UI supports per-request selection of `codeformer` or `gfpgan`. They use already-installed PyTorch/facexlib/OpenCV and existing weights from `models/`, verified against `extra-provenance.json`. Missing or mismatched weights produce explicit errors. Nothing downloads on startup or inference. No second AI framework is required.

CUDA is chosen when available with `device: auto`; otherwise CPU. CUDA/OOM inference errors retry on CPU in auto mode. `device: cpu` forces CPU. ModelManager holds one model role at a time, loads only upon demand, unloads on a role switch and after 120 seconds idle. Aligned masks and restored face arrays cache inference results so sliders do not rerun heavy models. Status includes device, loading role, loaded role and fallback explanation. All Retouch jobs execute sequentially; they wait for an already-active Upscale job to finish.

Parsing aligns faces to 512×512 using five landmarks and maps masks/deltas back to the source without changing geometry. All 19 classes remain cached internally. Skin processing excludes eyes (when preserved), eyebrows, lips/mouth, nose and hair. Additional conservative landmark guards protect central features. Masks are eroded/feathered while a hard semantic support prevents interpolation from changing protected pixels. Restoration blends only a local face delta, preserves alpha and does not replace the whole photo.

In Manual mode, Preserve Identity caps blending and protects features; it is not a mathematical identity guarantee. Automatic blemish candidates are conservative small dark/red spots and may include permanent marks, so the option defaults off. Manual strokes intersect skin support. Visual quality should be reviewed on the user's own photos before choosing stronger settings.

## API contract

All routes belong to `/api/retouch/` and inherit the loopback server's Host/Origin checks and `X-Studio-Token` authentication for mutations.

- GET `status`: model/device/busy/debug status and local session token; `?job=<id>` returns progress, result or structured error.
- POST `image`: binary PNG/JPEG/WebP; optional `X-Retouch-Document` updates the source revision. Returns `{document,revision}`. Upload limit 256 MB / 50 MP.
- POST `analyze`: `{document,revision}`. Returns `{job}`; completed result includes faces with bbox, confidence, five landmarks, size and cached flag. Detection never changes the photo.
- POST `preview` / `apply`: `{document,revision,settings}`. Returns `{job}`; completed result includes PNG URL/id/dimensions. Settings use smooth/blemish/restore/strength 0–100, texture/eyes/hair/identity/auto booleans, and normalized manual strokes `{x,y,r}`.
- GET `result/<document>/<file>`: strictly validated output PNG or development overlay. Source files and arbitrary paths are inaccessible.
- POST `cancel`: `{job}`. Cancellation is checked between inference stages; a running model call finishes safely first.
- POST `release`: `{document}`. Deletes only that session; during inference marks cancellation and defers deletion until the worker releases it.
- POST `unload`: `{}`. Explicitly releases Retouch model cache when idle.

Results/errors are structured; UI can return to ordinary editing after failures. Revision mismatch rejects stale requests. Geometry/edit changes upload one new source revision, preserving committed snapshots needed by Undo/Redo. Slider changes reuse the current document and analysis without resending the photo.

## Storage and development

At most four active documents. Each stores source PNG, the latest preview, up to 20 full results / 256 MB and optional overlays in a dedicated `rona-retouch-*` OS temporary folder. Server memory keeps semantic arrays and one loaded model, not all full-resolution result images. Browser memory keeps original/current render and one decoded AI snapshot. Releasing a document or normal process exit cleans the temporary folder. No Retouch persistence to Upscale History in this stage.

`development_debug: true` enables skin/eyes/eyebrows/lips/hair overlays only when `RONA_RESOURCE_DIR` is absent. Packaged production runtime sets that variable, hiding the UI and rejecting mask access. Set the flag false for a source-run production environment as well. Debug overlays visualize raw semantic classes; protected effective masks additionally erode and exclude landmark guard areas.

Source implementation only: the existing portable executable/ZIP was not rebuilt in this stage. Any future portable build must include this package/config, its frontend files, existing model weights and adapter dependencies.

References for existing compatible model implementations: [facexlib ParseNet](https://github.com/xinntao/facexlib/blob/master/facexlib/parsing/__init__.py), [CodeFormer](https://github.com/sczhou/CodeFormer), [19-class face parsing labels](https://github.com/zllrunning/face-parsing.PyTorch/blob/master/face_dataset.py).

## Automatic restoration (updated)

Retouch UI defaults to Automatic / CodeFormer with 70% blend and fidelity 0.8. GFPGAN is selectable; its fidelity control is hidden. Manual retains skin smoothing and optional automatic/manual blemish marks, with model-specific fidelity. Entering Retouch with a photo runs analysis and an automatic preview, without committing history. Apply creates one undoable step; its subsequent analysis does not automatically stack another restoration.

Automatic restoration uses the existing Upscale weights read-only but an independent Retouch implementation. Full facial features use a feathered facial mask; hair, background and source alpha remain unchanged. There is no x2 resize. Preview and Apply preserve source resolution (up to the existing 50 MP upload limit); processing each aligned face stays 512x512, while full-image PNG encoding/display can take longer and use more RAM on large photos. Manual skin masks keep their existing feature protections. Skin texture smoothing now retains 70% high-frequency texture rather than 92%.

Settings add `mode` (automatic/manual), `model` (codeformer/gfpgan) and `fidelity` (0–1). Old API requests default to manual. Each document revision owns its faces. Each face retains only its latest restored output, keyed by model and CodeFormer fidelity; blend changes reuse that output. A model or fidelity change replaces it, limiting memory. Model roles include the chosen restorer, so model switches unload the prior model. Before returns to the retained temporary preview; Cancel releases it. Lihat wajah centers/zooms the first detected face.

## Retouch Before/After comparison

The Retouch canvas now has a range slider and draggable vertical divider. Before is a single retained canvas copy of the immediate pre-Retouch image (including previous crop/filter/adjust edits), not the raw original. After uses the temporary preview or latest applied result. The comparison can be toggled off to view the entire After image, and it hides for other tools and while holding the original Before button. Opening another photo releases the retained comparison canvas. The comparison affects only the display canvas; model input, committed snapshots, and export use the independent currentPreview canvas and never include the split or divider. This adds one source-sized canvas to browser memory while comparison is retained.

### Navigation cache

Leaving Retouch now pauses pending work and hides overlays without discarding the analyzed faces, manual marks or completed preview. Returning to the same source revision reuses that preview when settings match, with no upload/analysis/inference request. A cached no-face result also remains valid. Opening another photo releases the prior document and caches. Changes to the actual rendered source still invalidate its analysis to avoid applying obsolete masks/coordinates. The cache remains temporary for the current editor session. The comparison controls are now a compact centered pill, with a 26 px divider handle.

## Shared persistent History

`/history` is the common history UI for Retouch and Upscale. `unified_history.py` adapts existing `Studio.history*` methods without changing the Upscale inference/store. The common page includes module filters, last-edited module/date, grid downloads, results/photos/model-cache views, and Edit choices for Retouch or Upscale. Existing `/api/history/*` endpoints remain supported. Upscale receives only a new navigation/import adapter; its original scripts and processing code are unchanged.

Retouch persists to `<Studio data root>/retouch-history/<photo id>/`: the raw uploaded source, an EXIF-oriented processing copy, versioned project recipes/parameters/results, and shared AI snapshot assets. Apply/Export saves a version; Simpan also saves the current rendered recipe. Slider-only temporary AI previews are never archived as final results. Identical recipes reuse the saved version; native Retouch reopening restores the source, recipe, controls, and AI snapshots. Individual results can be deleted; shared snapshots are retained until their final referencing version is removed. Cleaning model cache preserves snapshots needed for continuing Retouch edits. Files in the user's source folders, model weights and presets are excluded from deletion. Existing source-stage pending saves remain visible as photos and can be removed.

Same-module Edit restores its native configuration/project. Cross-module Edit imports the chosen completed result, with a new owned source copy; previous results remain intact. The frontend follows a short-lived server handoff id instead of arbitrary file URLs. Upscale's existing 12 MP/32 MB/opaque-image restrictions remain: preparing a compatible copy requires an explicit choice in the Edit dialog. Large photos are resized with preserved proportions and transparency is composited on white in that copy. Retouch keeps its 50 MP limit. `/api/library/*` mutations reuse the loopback Host/Origin/token checks and globally reject deletion/Edit while any module is processing. All deletes require a fresh size/fingerprint preview.

This change updates source files only; the existing portable EXE/ZIP has not been rebuilt. Browser interaction testing is reserved for the user. Automated coverage checks persistent restart/recipe/AI-asset restoration, native and cross-module imports, compatibility preparation, scoped deletion, cache cleanup, shared asset references, route/authentication, frontend save sequencing and failure handling.
