# Recommended models (local Ollama)

## Picks by job

| Job | Model | Tag | Size (Q4 approx) | Why |
| --- | --- | --- | --- | --- |
| **Document → JSON (primary)** | NuExtract3 | `numind/nuextract3` | 4B · ~3–4 GB | Purpose-built structured extraction: template mode with typed fields (`number`, `date-time`, `verbatim-string`), OCR included, multilingual, single-phase. Qwen3-VL based — strong JSON adherence |
| **OCR only (two-phase)** | LightOnOCR-2 | `maternion/LightOnOCR-2:1b` | 1B · ~1–2 GB | State-of-the-art OCR at 1B params; fastest option. Feed its text to a text model for JSON |
| OCR alternative | DeepSeek-OCR | `deepseek-ocr:3b` | 3B · ~2–3 GB (F16 6.7 GB) | Token-efficient OCR; markdown + grounding modes |
| OCR + extraction alternative | GLM-OCR | `glm-ocr:q8_0` | — | Two-phase OCR → gemma extraction |
| **Text path (digital PDFs)** | any instruct model you already run | `gemma4` / `qwen2.5-coder:14b` | — | `pypdf` text → JSON; most accurate path, no vision needed. Most utility bills are digital PDFs |
| Zero-install smoke test | gemma4 | `gemma4` (already installed) | 7.5B Q4 · ~5–6 GB | Works today; constrain with `format` JSON schema since Gemma is shakier at strict JSON |

## Defaults in the app

- `OLLAMA_MODEL=numind/nuextract3` — single-phase default
- `OLLAMA_OCR_MODEL=maternion/LightOnOCR-2:1b` — optional two-phase mode
  (OCR → text model), used automatically when the primary parse fails
- `OLLAMA_TEXT_MODEL=gemma4` — digital-PDF text extraction and phase 2

## Extraction settings

- Ollama `format` = JSON schema, `temperature: 0`, `stream: false`
- PDFs: `pypdf` text first; if empty → render page to PNG at **~1540 px longest
  side** (LightOnOCR's recommendation; helps all vision models)
- One page per image, first 2 pages only (bills are short); `num_ctx` 8k is plenty
- Timeout 60–120 s for vision; one retry via the two-phase path on parse failure

## Hardware fit

- The maintainer's Ollama host already runs a 7.5B Q4, so the 4B and 1B picks
  are comfortable
- Install: `ollama pull numind/nuextract3` and
  `ollama pull maternion/LightOnOCR-2:1b`
- Before locking the default, run 2–3 real bills through NuExtract3 vs the
  two-phase path; `OLLAMA_MODEL` makes swapping trivial
