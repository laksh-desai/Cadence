# MedASR local transcription — one-time setup

Cadence transcribes your dictation using Google's MedASR model, running entirely
on this laptop — no audio or text ever leaves the machine for this feature. The
model itself is free, but Google requires a one-time Hugging Face sign-in and
terms acceptance before it can be downloaded. This is a few minutes of clicking,
no code.

## 1. Create a free Hugging Face account

Go to [huggingface.co](https://huggingface.co) and sign up (or sign in if you
already have one).

## 2. Accept MedASR's usage terms

1. Visit [huggingface.co/google/medasr](https://huggingface.co/google/medasr)
   while signed in.
2. You'll see a terms-acceptance prompt (Google's "Health AI Developer
   Foundations" terms). Read and accept it — this is a one-time click per
   Hugging Face account.

## 3. Create an access token

1. Go to [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).
2. **Create new token** → name it anything (e.g. "cadence") → type **Read** is
   enough, no write access needed.
3. Copy the token — you won't be able to see it again after leaving the page.

## 4. Configure Cadence

Copy `app/transcribe/hf_config.example.yaml` to `app/transcribe/hf_config.yaml`
(same folder) and paste the token in:

```yaml
hf_token: "paste your token here"
```

(`hf_config.yaml` is gitignored — it's a personal credential, never committed.)

## 5. Restart and verify

Close and reopen Cadence. The first launch after this will take noticeably
longer than usual (downloading ~400MB once) — subsequent launches load the
cached model from disk and start in a few seconds. If the mic button works and
produces text after a test recording, setup is complete.

## What this model does and doesn't do

- Transcription happens locally, after the model is downloaded — nothing about
  your dictation audio or its text is sent to Hugging Face, Google, or anywhere
  else once setup is done. The one-time *download* of the model weights
  themselves does go over the network, the same as any one-time model download
  already part of this app's setup (Ollama/MedGemma worked the same way).
- Per Google's terms for this model, transcription output "is not intended to
  directly inform clinical diagnosis... without independent verification" —
  this is exactly why, as with every Cadence note, a clinician reviews and signs
  off before anything is finalized. The transcript is a draft input to note
  generation, never the final clinical record on its own.

## If something looks wrong

- **Mic button is disabled with an error mentioning Hugging Face**: token
  missing or not yet configured — redo step 4.
- **Error mentions the token was rejected, or terms not accepted**: re-check
  step 2 was done on the *same* Hugging Face account the token in step 3 was
  created under.
- **First launch takes a long time / seems stuck**: that's the one-time ~400MB
  download. Check your network connection; subsequent launches are fast.
- **Everything else in the app still works even if this isn't set up** — the
  patient roster, note generation, and Sheets sync are unaffected by MedASR
  setup status. Only the mic/dictation buttons depend on it; typing always works.
