# Pending Tasks & HD-Transcription Plan

## Core Plan: Improving LaTeX Quality (Max 2 API Calls)

### 1. Vision Model Upgrade
- **Action**: Switch `NoteService.transcribe_note` from Gemini Flash to **Gemini 1.5 Pro**.
- **Reason**: Pro has significantly higher spatial reasoning for mathematical handwriting (distinguishing $v$ vs $\nu$, $2$ vs $z$, etc.).

### 2. "Visual-to-Logical" Prompting
- **Action**: Update the Gemini prompt to require a brief structural description before providing LaTeX.
- **Goal**: Force the model to "understand" the mathematical context before jumping to transcription.

### 3. Integrated Proofreading (DeepSeek)
- **Action**: Merge the LaTeX repair logic into the existing **DeepSeek Reasoner** (Grading/Solving) prompt.
- **Instruction to AI**: "The input LaTeX comes from an OCR process. Your first internal step is to mathematically proofread and fix transcription errors before you begin your analysis."
- **Benefit**: No extra API calls or latency, but leverages DeepSeek's high-level reasoning to "deduce" the correct symbols.

### 4. Studio UI Enhancements
- [ ] Add "Auto-save" on editor pause.
- [ ] Add keyboard shortcuts for Metadata drawer.
- [ ] Implement a "Force AI Repair" button for Mode B (Blank) notes.

---
*Last updated: 2026-03-17*
