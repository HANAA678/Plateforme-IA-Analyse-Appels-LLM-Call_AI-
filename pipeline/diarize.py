import os
import torch
import soundfile as sf
from dotenv import load_dotenv
from pyannote.audio import Pipeline

load_dotenv()

_pipeline = None


def get_pipeline():
    global _pipeline

    if _pipeline is None:
        token = os.getenv("HF_TOKEN")
        if not token:
            raise ValueError("HF_TOKEN manquant dans .env")

        _pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            token=token
        )

    return _pipeline


def _extract_annotation(diarization):
    """
    pyannote peut retourner plusieurs types selon la version :
      - Annotation    (ancien) : a itertracks directement
      - DiarizeOutput (nouveau) : wrapper, l'Annotation est dans .diarization
    """
    # Cas 1 : a directement itertracks -> c'est une Annotation
    if hasattr(diarization, "itertracks"):
        return diarization

    # Cas 2 : DiarizeOutput -> l'Annotation est dans l'attribut .diarization
    if hasattr(diarization, "diarization"):
        return diarization.diarization

    # Cas 3 : chercher le premier attribut qui a itertracks
    for attr_name in vars(diarization):
        attr = getattr(diarization, attr_name)
        if hasattr(attr, "itertracks"):
            return attr

    raise TypeError(
        f"Impossible d'extraire l'Annotation depuis {type(diarization)}. "
        f"Attributs disponibles : {list(vars(diarization).keys())}"
    )


def diarize_audio(file_path: str, total_duration: float):

    if total_duration <= 0:
        return {
            "agent_talk_pct":      0,
            "client_talk_pct":     0,
            "silence_pct":         0,
            "silence_max_sec":     0,
            "interruptions_count": 0,
            "silences":            [],
            "diarization":         []
        }

    pipeline = get_pipeline()

    # Charger l'audio avec soundfile (evite torchcodec / FFmpeg)
    waveform_np, sample_rate = sf.read(file_path, dtype="float32", always_2d=True)
    waveform_tensor = torch.tensor(waveform_np.T)   # (time, ch) -> (ch, time)

    audio_input = {
        "waveform":    waveform_tensor,
        "sample_rate": sample_rate
    }

    # Lancer la diarisation
    raw_output = pipeline(audio_input)
    print("TYPE DIARIZATION:", type(raw_output))

    # Normaliser vers une Annotation avec itertracks
    annotation = _extract_annotation(raw_output)

    # Extraire les segments
    segments      = []
    speaker_times = {}

    for turn, _, speaker in annotation.itertracks(yield_label=True):
        duration = turn.end - turn.start

        segments.append({
            "speaker":   speaker,
            "start_sec": round(turn.start, 2),
            "end_sec":   round(turn.end,   2),
            "pct_width": round((duration / total_duration) * 100, 1)
        })

        speaker_times[speaker] = speaker_times.get(speaker, 0) + duration

    # Identifier agent (premier locuteur) et client
    speakers = sorted(speaker_times.keys())

    agent_speaker  = speakers[0] if len(speakers) > 0 else None
    client_speaker = speakers[1] if len(speakers) > 1 else None

    agent_time  = speaker_times.get(agent_speaker,  0)
    client_time = speaker_times.get(client_speaker, 0)

    talked_time  = agent_time + client_time
    silence_time = max(0, total_duration - talked_time)

    # Detecter les silences (gaps entre segments >= 3s)
    silences    = []
    sorted_segs = sorted(segments, key=lambda x: x["start_sec"])

    for i in range(1, len(sorted_segs)):
        gap = sorted_segs[i]["start_sec"] - sorted_segs[i - 1]["end_sec"]
        if gap >= 3:
            silences.append({
                "start_sec":    round(sorted_segs[i - 1]["end_sec"], 2),
                "duration_sec": round(gap, 2),
                "type":         "hold"
            })

    # Compter les interruptions
    interruptions = 0
    for i in range(1, len(sorted_segs)):
        if sorted_segs[i]["start_sec"] < sorted_segs[i - 1]["end_sec"]:
            interruptions += 1

    silence_max = max((s["duration_sec"] for s in silences), default=0)

    return {
        "agent_talk_pct":      round((agent_time   / total_duration) * 100, 1),
        "client_talk_pct":     round((client_time  / total_duration) * 100, 1),
        "silence_pct":         round((silence_time / total_duration) * 100, 1),
        "silence_max_sec":     int(silence_max),
        "interruptions_count": interruptions,
        "silences":            silences,
        "diarization":         segments
    }
