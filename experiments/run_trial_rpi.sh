#!/usr/bin/env bash
# Corrida del trial de generacion de acciones en la Raspberry Pi 5 "inmoov".
#
# Deja registrada la configuracion exacta usada para los datos del paper, para no
# depender de pegar una linea larga de variables de entorno a mano.
#
#   ./experiments/run_trial_rpi.sh              # 4 comandos x 3 repeticiones
#   ./experiments/run_trial_rpi.sh --reps 5     # cualquier argumento pasa al harness
set -euo pipefail

cd "$(dirname "$0")/.."

# Micrófono USB AB13X en card 2. El dispositivo ALSA "default" son las salidas HDMI,
# asi que hay que apuntar explicitamente a la tarjeta de captura.
export MIC_DEVICE="${MIC_DEVICE:-plughw:2,0}"

# Umbral de VAD calibrado con ~/calibrar_mic.py: piso de ruido ~60, voz sobre 1100.
export VAD_THRESHOLD="${VAD_THRESHOLD:-400}"

# El modelo solo ve la interfaz articular generalizada, sin rutinas predefinidas.
export ROBOT_TOOLS_MODE="${ROBOT_TOOLS_MODE:-joints_only}"

# Enter en el terminal reemplaza al boton A del mando (comodo por SSH).
export GAMEPAD_DEVICE="${GAMEPAD_DEVICE:-keyboard}"

# Whisper como ASR, que es lo que reporta el paper.
export OPENAI_STT_MODEL="${OPENAI_STT_MODEL:-whisper-1}"

# Sin ROBOT_DRY_RUN: las consignas viajan por serial al Arduino Mega, que las acusa.
# Los servos van desconectados, de modo que no se produce movimiento articulado.

exec python3 experiments/action_generation_trial.py "$@"
