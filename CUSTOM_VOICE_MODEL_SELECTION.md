# कस्टम voice-design मॉडल चयन

**अभी का निष्कर्ष:** Kokoro का English preset CPU path पहले वास्तविक WAV smoke में पास हुआ। Prompt से आवाज़ डिजाइन करने के लिए Qwen3-TTS VoiceDesign भी अब एक सीमित, वास्तविक CPU smoke में पास हुआ: pinned checkpoint के native BF16 dtype के साथ profile-backed inference ने 24-kHz mono PCM16 का 3.2-second WAV बनाया और सातों objective smoke checks तथा स्वतंत्र WAV inspection पास की। पहले का default FP32 load उसी 10-GiB process-tree RSS guard से रुक गया था; सीमा नहीं बढ़ाई गई। यह उसी 1.7B मॉडल का memory-conscious dtype load है, कोई अलग छोटा model architecture नहीं। यह एक English sample पर path verification है—subjective naturalness, उच्चारण, speaker identity, हर भाषा/control, दीर्घकालीन stability, या दूसरे computers की guarantee नहीं। Installed Skill में केवल Kokoro `preset` और Qwen `voice_design` उपलब्ध हैं; Chatterbox/reference clone और Qwen CustomVoice preset वास्तविक WAV acceptance तक छिपे/अस्वीकृत हैं। [1] [2] [3]

**MOSS-VoiceGenerator अभी default नहीं होगा।** उसका मुख्य checkpoint अकेले 4.23 GB दिखता है, लेकिन official processor एक अलग 1.77B-parameter MOSS-Audio-Tokenizer भी load करता है। दोनों repositories का reported storage मिलाकर लगभग 11.33 GB है; CPU float32 में parameter payload लगभग 15.55 GB बनता है—runtime overhead, temporary copies और activations से पहले। इसलिए इसे download/load नहीं किया गया और बिना बेहतर verified loading strategy के inference नहीं चलाया जाएगा। [4] [5] [6]

## विकल्प और सीमाएँ

- **Kokoro preset:** उपलब्ध voices और speed controls वाला स्थानीय preset path; एक English CPU profile (`af_heart`) का WAV acceptance पास है। यह prompt से नया speaker identity बनाने का विकल्प नहीं है। [7]
- **Qwen VoiceDesign:** natural-language voice description से नया voice design करने वाला documented API और Apache-2.0 model। Pinned snapshot में main `model.safetensors` के 404 tensors BF16 हैं; speech-tokenizer weights F32 हैं। Backend अब VoiceDesign CPU load में `dtype="bfloat16"` मांगता है। 10-GiB guard और 300-second deadline बदले बिना एक profile-backed English sample पास हुआ; exact peak RSS report में दर्ज नहीं, इसलिए कोई peak संख्या दावा नहीं है। पहले FP32 load guard पर रुका था। [1] [2] [3]
- **Qwen CustomVoice preset:** अलग model variant और speaker-preset route है; वास्तविक WAV smoke नहीं हुआ, इसलिए installed Skill के profile creation और runner से हटाया गया है। [1] [2]
- **Chatterbox:** audited code/preset/reference-audio route उपलब्ध था, लेकिन इस project के host पर इसका real inference स्वीकार नहीं हुआ। इसे installed Skill के profile creation और runner से हटाया गया है; इसे prompt-based design नहीं कहा जाएगा। [10]
- **MOSS-VoiceGenerator:** description-based identity, emotion, speed और pitch controls तथा CPU loader path documented हैं; मगर पूरा stack 1.7B/2.1B main model के अलावा अलग 1.77B audio-tokenizer मांगता है। मौजूदा host पर resource risk ऊँचा है। [4] [5] [6]
- **VoxCPM2:** voice-design listening evidence inspected candidates में मजबूत है: authors' blind test में N-MOS 4.48±0.04 और I-MOS 4.50±0.03 रिपोर्ट हुए। यह सीमित paper-specific test है, universal leaderboard नहीं। Official Python runtime CUDA ≥12.0 और paper RTX 4090 पर प्रदर्शन बताता है; इसलिए मौजूदा CPU-only host का विकल्प नहीं। [8] [9]
- **अन्य audited variants:** Chatterbox Turbo, CosyVoice3, Fish Audio S1 Mini और IndexTTS-2 के audited local workflows इस feature के text-only speaker-design criterion को पूरा नहीं करते या उनमें gating/license/runtime सीमाएँ हैं। [10] [11] [12] [13]

## Product behavior के लिए निर्णय

Installed Skill केवल उन दो mode pairs को expose करती है जिनके real WAV acceptance checks पास हैं: `kokoro/preset` और `qwen3_tts/voice_design`। Qwen voice-description profile को local store में save करके reuse किया जा सकता है; इससे वही recipe फिर लागू होती है, लेकिन बिल्कुल एक जैसी speaker identity की guarantee नहीं। Unverified/unsupported profile modes CLI से create नहीं किए जा सकते और synthesis runner पुराने ऐसे profiles को reject करता है। Unsupported controls चुपचाप ignore नहीं होते।

Qwen VoiceDesign CPU adapter checkpoint का native BF16 load करता है और configured resource policy नहीं बदलता: RAM preflight, 10-GiB monitored process-tree RSS cap, two CPU threads और finite 300-second smoke deadline। किसी host पर preflight, model load, timeout या WAV acceptance fail हो तो failure को साफ बताना है—memory cap बढ़ाना या remote service पर स्वतः switch करना नहीं।

## References

[1]: https://huggingface.co/api/models/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign "Qwen3-TTS VoiceDesign official Hub metadata"
[2]: https://huggingface.co/api/models/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign/tree/main?recursive=true&expand=true "Qwen3-TTS VoiceDesign official file tree"
[3]: https://huggingface.co/Qwen/Qwen3-TTS-Tokenizer-12Hz "Qwen3-TTS 12Hz speech tokenizer model card"
[4]: https://huggingface.co/api/models/OpenMOSS-Team/MOSS-VoiceGenerator "MOSS-VoiceGenerator official Hub metadata"
[5]: https://huggingface.co/api/models/OpenMOSS-Team/MOSS-Audio-Tokenizer "MOSS-Audio-Tokenizer official Hub metadata"
[6]: https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer "MOSS-Audio-Tokenizer official model card"
[7]: https://huggingface.co/hexgrad/Kokoro-82M "Kokoro-82M official model card"
[8]: https://arxiv.org/html/2606.06928v1 "VoxCPM2 technical report"
[9]: https://github.com/OpenBMB/VoxCPM "OpenBMB VoxCPM official repository"
[10]: https://huggingface.co/ResembleAI/chatterbox-turbo "Chatterbox Turbo model card"
[11]: https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512 "CosyVoice3 model card"
[12]: https://huggingface.co/fishaudio/s1-mini "Fish Audio S1 Mini model card"
[13]: https://github.com/index-tts/index-tts "IndexTTS official repository"
