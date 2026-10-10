import hashlib, io, json, wave
import pytest
from voiceover_pipeline import (PipelineError, PipelineRequest, chunk_text, run_pipeline,
    select_adapter, validate_request, _join_wavs, _wav_info)

class Adapter:
    engine_id = 'kokoro'
    supported_languages = {'en', 'ur'}
    available = True
    def __init__(self, rate=16000, channels=1, width=2, fail=None):
        self.rate, self.channels, self.width, self.fail, self.calls = rate, channels, width, fail, []
    def synthesize_wav(self, text, *, language, voice_id, speed=1.0, seed=None):
        self.calls.append((text, language, voice_id, speed, seed))
        if self.fail: raise RuntimeError(self.fail)
        stream = io.BytesIO()
        with wave.open(stream, 'wb') as w:
            w.setnchannels(self.channels); w.setsampwidth(self.width); w.setframerate(self.rate)
            w.writeframes(b'\0' * self.channels * self.width * 80)
        return stream.getvalue()

def req(**kw):
    values = dict(request_id='req_1', text='hello world', language='EN', voice_id='voice_1', chunk_chars=20)
    values.update(kw)
    return PipelineRequest(**values)

def test_d0_101_valid_request_normalizes_language_and_trims_text():
    x = validate_request(req(text='  hello  ', language='EN'))
    assert (x.text, x.language) == ('hello', 'en')

def test_d0_102_request_id_must_be_safe():
    with pytest.raises(PipelineError, match='INVALID_REQUEST_ID'): validate_request(req(request_id='../x'))

def test_d0_103_empty_text_rejected():
    with pytest.raises(PipelineError, match='INVALID_TEXT'): validate_request(req(text='  '))

def test_d0_104_text_hard_limit_rejected():
    with pytest.raises(PipelineError, match='TEXT_TOO_LONG'): validate_request(req(text='a' * 1_000_001))

def test_d0_105_language_validation():
    with pytest.raises(PipelineError, match='INVALID_LANGUAGE'): validate_request(req(language='u r'))

def test_d0_106_voice_id_validation():
    with pytest.raises(PipelineError, match='INVALID_VOICE_ID'): validate_request(req(voice_id='../voice'))

def test_d0_107_chunk_limit_validation():
    for value in (True, 0, -1, 100001, '2'):
        with pytest.raises(PipelineError, match='INVALID_CHUNK_LIMIT'): validate_request(req(chunk_chars=value))

def test_d0_108_speed_bounds_and_bool_rejected():
    for value in (True, 0.49, 2.01, float('nan'), float('inf')):
        with pytest.raises(PipelineError, match='INVALID_SPEED'): validate_request(req(speed=value))

def test_d0_109_seed_bounds_and_bool_rejected():
    for value in (True, -1, 2147483648):
        with pytest.raises(PipelineError, match='INVALID_SEED'): validate_request(req(seed=value))

def test_d0_110_output_name_rejects_traversal_and_separators():
    for name in ('../x.wav', '/tmp/x.wav', 'folder/x.wav', 'x\\y.wav', 'x:bad.wav'):
        with pytest.raises(PipelineError, match='INVALID_OUTPUT_NAME'): validate_request(req(output_name=name))

def test_d0_111_chunking_respects_limit_and_order():
    chunks = chunk_text('one two three four', 7)
    assert all(len(x) <= 7 for x in chunks) and ' '.join(chunks) == 'one two three four'

def test_d0_112_oversized_word_is_split_without_character_loss():
    assert chunk_text('abcdefghij', 3) == ['abc', 'def', 'ghi', 'j']

def test_d0_113_adapter_selection_is_deterministic():
    class A(Adapter): engine_id='zengine'
    class B(Adapter): engine_id='aengine'
    assert select_adapter(validate_request(req()), [A(), B()]).engine_id == 'aengine'

def test_d0_114_unavailable_adapter_not_selected():
    a = Adapter(); a.available = False
    with pytest.raises(PipelineError, match='NO_COMPATIBLE_ENGINE'): select_adapter(validate_request(req()), [a])

def test_d0_115_duplicate_engine_ids_rejected():
    with pytest.raises(PipelineError, match='DUPLICATE_ADAPTER_ENGINE_ID'): select_adapter(validate_request(req()), [Adapter(), Adapter()])

def test_d0_116_preferred_engine_does_not_silently_fallback():
    with pytest.raises(PipelineError, match='PREFERRED_ENGINE_UNAVAILABLE'): select_adapter(validate_request(req(preferred_engine='qwen3_tts')), [Adapter()])

def test_d0_117_valid_wav_metadata():
    info = _wav_info(Adapter().synthesize_wav('hi', language='en', voice_id='v'))
    assert info.sample_rate == 16000 and info.frames == 80 and info.duration_seconds == 0.005

def test_d0_118_corrupt_wav_rejected():
    with pytest.raises(PipelineError, match='AUDIO_INVALID_WAV'): _wav_info(b'not wav')

def test_d0_119_wav_format_mismatch_rejected():
    with pytest.raises(PipelineError, match='AUDIO_FORMAT_MISMATCH'):
        _join_wavs([Adapter(rate=16000).synthesize_wav('a', language='en', voice_id='v'), Adapter(rate=22050).synthesize_wav('b', language='en', voice_id='v')])

def test_d0_120_joined_wav_duration_is_sum_of_chunks():
    payload, info = _join_wavs([Adapter().synthesize_wav('a', language='en', voice_id='v') for _ in range(3)])
    assert info.frames == 240 and info.duration_seconds == 0.015 and _wav_info(payload) == info

def test_d0_121_pipeline_writes_atomic_final_artifacts(tmp_path):
    result = run_pipeline(req(), [Adapter()], tmp_path)
    assert (tmp_path / 'voiceover.wav').is_file() and (tmp_path / 'voiceover.wav.manifest.json').is_file()
    assert not list(tmp_path.glob('*.tmp')) and not list(tmp_path.glob('.*.tmp'))

def test_d0_122_manifest_sha256_matches_audio(tmp_path):
    result = run_pipeline(req(), [Adapter()], tmp_path)
    assert hashlib.sha256((tmp_path / 'voiceover.wav').read_bytes()).hexdigest() == result.sha256

def test_d0_123_manifest_records_audio_metadata_and_engine(tmp_path):
    result = run_pipeline(req(), [Adapter()], tmp_path)
    data = json.loads((tmp_path / 'voiceover.wav.manifest.json').read_text())
    assert data['engine_id'] == 'kokoro' and data['audio']['sha256'] == result.sha256 and data['audio']['format'] == 'wav'

def test_d0_124_provider_exception_does_not_leak_message(tmp_path):
    with pytest.raises(PipelineError, match='SYNTHESIS_FAILED') as err: run_pipeline(req(), [Adapter(fail='secret-token-123')], tmp_path)
    assert 'secret-token-123' not in str(err.value)

def test_d0_125_chunking_empty_and_nul_rejected():
    for text in (' ', 'x\x00y'):
        with pytest.raises(PipelineError, match='INVALID_TEXT'): chunk_text(text, 10)

def test_d0_126_output_resolves_inside_root(tmp_path):
    result = run_pipeline(req(output_name='result.wav'), [Adapter()], tmp_path)
    assert result.output_path.startswith(str(tmp_path.resolve()))

def test_d0_127_invalid_adapter_metadata_rejected():
    a = Adapter(); a.supported_languages = ['en', 1]
    with pytest.raises(PipelineError, match='INVALID_ADAPTER_LANGUAGES'): select_adapter(validate_request(req()), [a])

def test_d0_128_empty_wav_rejected():
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
    with pytest.raises(PipelineError, match='AUDIO_EMPTY_OR_TRUNCATED'): _wav_info(stream.getvalue())

def test_d0_129_existing_output_is_replaced_only_after_successful_synthesis(tmp_path):
    target = tmp_path / 'voiceover.wav'; target.write_bytes(b'old-audio')
    with pytest.raises(PipelineError, match='SYNTHESIS_FAILED'): run_pipeline(req(), [Adapter(fail='failure')], tmp_path)
    assert target.read_bytes() == b'old-audio'

def test_d0_130_end_to_end_multi_chunk_invokes_provider_in_order(tmp_path):
    a = Adapter(); result = run_pipeline(req(text='one two three four', chunk_chars=7), [a], tmp_path)
    assert result.chunks == len(a.calls) == 3
    assert [x[0] for x in a.calls] == ['one two', 'three', 'four']


def test_profile_manifest_records_only_profile_identity_and_mode(tmp_path):
    request = req(preferred_engine='kokoro', voice_profile_id='news_reader', voice_mode='preset')
    run_pipeline(request, [Adapter()], tmp_path)
    manifest = json.loads((tmp_path / 'voiceover.wav.manifest.json').read_text())
    assert manifest['voice_profile_id'] == 'news_reader' and manifest['voice_mode'] == 'preset'
    assert 'voice_description' not in manifest and 'reference_asset' not in manifest


def test_profile_metadata_requires_profile_id_and_supported_engine_mode():
    with pytest.raises(PipelineError, match='VOICE_PROFILE_ID_REQUIRED'):
        validate_request(req(voice_mode='preset'))
    with pytest.raises(PipelineError, match='VOICE_MODE_UNSUPPORTED'):
        validate_request(req(preferred_engine='kokoro', voice_profile_id='news_reader', voice_mode='voice_design'))


def test_legacy_manifest_shape_remains_profile_free(tmp_path):
    run_pipeline(req(), [Adapter()], tmp_path)
    manifest = json.loads((tmp_path / 'voiceover.wav.manifest.json').read_text())
    assert 'voice_profile_id' not in manifest and 'voice_mode' not in manifest
