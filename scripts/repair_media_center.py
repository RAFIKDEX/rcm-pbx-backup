#!/usr/bin/env python3
import json
import os
import shutil
import wave
from datetime import datetime

BASE = "/etc/asterisk"
MEDIA_FILE = os.path.join(BASE, "rcm_media_center.json")
IVR_FILE = os.path.join(BASE, "rcm_ivrs.json")
ANN_FILE = os.path.join(BASE, "rcm_announcements.json")
QUEUE_FILE = os.path.join(BASE, "rcm_queues.json")
RING_FILE = os.path.join(BASE, "rcm_ring_groups.json")


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4, ensure_ascii=False)


def unique_id(existing):
    idx = 1
    while True:
        candidate = f"prompt_repair_{idx}"
        if candidate not in existing:
            existing.add(candidate)
            return candidate
        idx += 1


def write_silence_wav(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 8000)


def unique_path(base_path, suffix):
    root, ext = os.path.splitext(base_path)
    candidate = f"{root}_{suffix}{ext or '.wav'}"
    idx = 1
    while os.path.exists(candidate):
        candidate = f"{root}_{suffix}_{idx}{ext or '.wav'}"
        idx += 1
    return candidate


def main():
    media = load_json(MEDIA_FILE, {"prompts": [], "moh_classes": []})
    ivrs = load_json(IVR_FILE, {"ivrs": []}).get("ivrs", [])
    announcements_data = load_json(ANN_FILE, {"announcements": []})
    announcements = announcements_data.get("announcements", [])
    queues = load_json(QUEUE_FILE, {"queues": []}).get("queues", [])
    rings_data = load_json(RING_FILE, {"groups": []})
    rings = rings_data if isinstance(rings_data, list) else rings_data.get("groups", [])

    prompts = media.setdefault("prompts", [])
    prompt_by_id = {p.get("id"): p for p in prompts}
    existing_ids = set(prompt_by_id)
    changed = []

    usage = {}
    for ivr in ivrs:
        pid = ivr.get("prompt_id")
        if pid:
            usage.setdefault(pid, set()).add("ivr")
    for ann in announcements:
        pid = ann.get("prompt_id")
        if pid:
            usage.setdefault(pid, set()).add("announcement")
    for queue in queues:
        pid = queue.get("custom_prompt")
        if pid:
            usage.setdefault(pid, set()).add("queue")
    for ring in rings:
        pid = ring.get("pre_ring_announcement")
        if pid:
            usage.setdefault(pid, set()).add("ring_group")

    for pid, types in usage.items():
        prompt = prompt_by_id.get(pid)
        if not prompt:
            continue

        sorted_types = sorted(types)
        primary = sorted_types[0]
        if len(sorted_types) == 1:
            if prompt.get("type") != primary:
                prompt["type"] = primary
                changed.append(f"{prompt.get('name')} categorized as {primary}")
            continue

        if prompt.get("type") not in types:
            prompt["type"] = primary
            changed.append(f"{prompt.get('name')} categorized as {primary}")

        for extra_type in sorted_types:
            if extra_type == prompt.get("type"):
                continue
            new_prompt = dict(prompt)
            new_prompt["id"] = unique_id(existing_ids)
            new_prompt["type"] = extra_type
            new_prompt["name"] = f"{prompt.get('name')}_{extra_type}"
            new_prompt["path"] = unique_path(prompt.get("path", ""), extra_type) if prompt.get("path") else ""
            new_prompt["created_at"] = datetime.now().isoformat()
            prompts.append(new_prompt)
            prompt_by_id[new_prompt["id"]] = new_prompt
            changed.append(f"duplicated {prompt.get('name')} for {extra_type}")
            if prompt.get("path") and os.path.exists(prompt["path"]):
                shutil.copy2(prompt["path"], new_prompt["path"])

            for ann in announcements:
                if extra_type == "announcement" and ann.get("prompt_id") == pid:
                    ann["prompt_id"] = new_prompt["id"]
            for queue in queues:
                if extra_type == "queue" and queue.get("custom_prompt") == pid:
                    queue["custom_prompt"] = new_prompt["id"]
            for ring in rings:
                if extra_type == "ring_group" and ring.get("pre_ring_announcement") == pid:
                    ring["pre_ring_announcement"] = new_prompt["id"]

    for prompt in prompts:
        path = prompt.get("path")
        if path and not os.path.exists(path):
            write_silence_wav(path)
            changed.append(f"created 1s silence placeholder for missing file {path}")

    seen_paths = {}
    for prompt in prompts:
        path = prompt.get("path")
        if not path:
            continue
        if path not in seen_paths:
            seen_paths[path] = prompt.get("id")
            continue
        new_path = unique_path(path, prompt.get("type") or "copy")
        if os.path.exists(path):
            shutil.copy2(path, new_path)
        else:
            write_silence_wav(new_path)
        prompt["path"] = new_path
        changed.append(f"split shared prompt file to {new_path}")

    save_json(MEDIA_FILE, media)
    save_json(ANN_FILE, announcements_data)
    print("media repair complete")
    for item in changed:
        print(f"- {item}")


if __name__ == "__main__":
    main()
