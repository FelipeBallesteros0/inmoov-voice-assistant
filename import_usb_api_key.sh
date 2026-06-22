#!/usr/bin/env bash
set -euo pipefail

USB_LABEL="${USB_LABEL:-USB16GB}"
API_KEY_FILENAME="${API_KEY_FILENAME:-api_key.txt}"
TARGET_PATH="${LOCAL_API_KEY_PATH:-$HOME/.config/rpi_voice_assistant/openai_api_key.txt}"
MOUNT_DIR="${USB_MOUNT_DIR:-$HOME/usb_mount}"

mounted_here=0
cleanup() {
  if [[ "$mounted_here" -eq 1 ]]; then
    umount "$MOUNT_DIR"
  fi
}
trap cleanup EXIT

mkdir -p "$(dirname "$TARGET_PATH")"
mkdir -p "$MOUNT_DIR"

source_path=""
for root in /media /mnt /run/media; do
  if [[ -f "$root/$USB_LABEL/$API_KEY_FILENAME" ]]; then
    source_path="$root/$USB_LABEL/$API_KEY_FILENAME"
    break
  fi
done

if [[ -z "$source_path" ]]; then
  mount -o ro "/dev/disk/by-label/$USB_LABEL" "$MOUNT_DIR"
  mounted_here=1
  if [[ -f "$MOUNT_DIR/$API_KEY_FILENAME" ]]; then
    source_path="$MOUNT_DIR/$API_KEY_FILENAME"
  fi
fi

if [[ -z "$source_path" ]]; then
  echo "No se encontro $API_KEY_FILENAME en el USB con label $USB_LABEL." >&2
  exit 1
fi

install -m 600 "$source_path" "$TARGET_PATH"
echo "API key copiada a $TARGET_PATH"
