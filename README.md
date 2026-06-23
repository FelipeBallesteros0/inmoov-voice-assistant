# Raspberry Voice Assistant

Asistente de voz para Raspberry Pi 5 controlado con un mando Xbox 360.

Flujo:

1. Primera pulsacion del boton `A`: entra en modo conversacion.
2. La Raspberry captura audio local, detecta fin de turno por silencio y envia el audio a OpenAI.
3. OpenAI transcribe, genera una respuesta y devuelve audio sintetizado.
4. La Raspberry reproduce la respuesta.
5. Segunda pulsacion del boton `A`: apaga el programa.

## Requisitos practicos

- Python 3.12+
- Acceso de lectura a `/dev/input/js0`
- Un comando de captura PCM que escriba audio crudo a `stdout`
- Un comando de reproduccion WAV
- Conectividad a `api.openai.com`

Este entorno no trae utilidades de audio instaladas. La app se configura con comandos externos para grabar y reproducir. Ejemplo tipico si instalas ALSA utils:

```bash
export RECORD_PCM_CMD='arecord -q -D {mic_device} -f S16_LE -c {channels} -r {rate} -t raw'
export PLAY_WAV_CMD='aplay -q -D {speaker_device} {path}'
```

## Variables principales

```bash
export OPENAI_CHAT_MODEL='gpt-5.5'
export OPENAI_STT_MODEL='gpt-4o-mini-transcribe'
export OPENAI_TTS_MODEL='gpt-4o-mini-tts'
export OPENAI_TTS_VOICE='coral'
export MIC_DEVICE='default'
export SPEAKER_DEVICE='default'
export GAMEPAD_DEVICE='/dev/input/js0'
export GAMEPAD_A_BUTTON_INDEX='0'
export USB_LABEL='USB16GB'
export API_KEY_FILENAME='api_key.txt'
export LOCAL_API_KEY_PATH="$HOME/.config/rpi_voice_assistant/openai_api_key.txt"
```

La API key se resuelve en este orden:

1. `OPENAI_API_KEY`
2. `LOCAL_API_KEY_PATH`
3. importacion desde un USB con `api_key.txt` en la raiz

## Function calling local

El asistente expone herramientas locales para hora/fecha, calculadora simple, notas, alarmas, servo de prueba e InMoov. Para el robot InMoov, el modelo solo ve `get_robot_status` y `set_robot_joints`: una funcion general que recibe pares `joint` + `angle_degrees` y mueve solo las articulaciones listadas. Las rutinas de dedos/manos quedan como comandos legacy del firmware, pero no se publican al LLM.

Ejemplo de argumentos para `set_robot_joints`:

```json
{
  "joints": [
    {"joint": "cabeza", "angle_degrees": 90},
    {"joint": "indice_der", "angle_degrees": 40}
  ]
}
```

La Raspberry valida nombres duplicados, articulaciones desconocidas y limites angulares antes de escribir por serial. El comando enviado al Arduino Mega usa indices compactos, por ejemplo `ROBOT JOINTS 6:90 17:40`, y espera una respuesta `OK JOINTS 2`.

Articulaciones controladas por el firmware actual: `lat_izq`, `lat_der`, `rotor_izq`, `rotor_der`, `bicep_izq`, `bicep_der`, `cabeza`, `mandibula`, `cuello`, `cuello_izq`, `cuello_der`, `pulgar_izq`, `indice_izq`, `medio_izq`, `anular_izq`, `meni_izq`, `pulgar_der`, `indice_der`, `medio_der`, `anular_der`, `meni_der`.

### Servo en Arduino

Configuracion por defecto:

```bash
export SERVO_SERIAL_PORT='/dev/serial/by-id/usb-Arduino__www.arduino.cc__0043_7513931383135120D090-if00'
export SERVO_SERIAL_BAUDRATE='115200'
```

Carga del sketch en un Arduino Uno:

```bash
export PATH="$HOME/.local/bin:$PATH"
arduino-cli core install arduino:avr
arduino-cli lib install Servo
arduino-cli compile --fqbn arduino:avr:uno arduino/servo_controller
arduino-cli upload -p /dev/ttyACM0 --fqbn arduino:avr:uno arduino/servo_controller
```

Comando de voz esperado:

```text
mueve el motor a 90 grados
```

La herramienta valida angulos enteros entre `0` y `180` grados y envia `SERVO <angulo>` por serial.

### InMoov en Arduino Mega

Configuracion por defecto:

```bash
export ROBOT_SERIAL_PORT='/dev/ttyUSB0'
export ROBOT_SERIAL_BAUDRATE='115200'
```

Carga del sketch en un Arduino Mega:

```bash
export PATH="$HOME/.local/bin:$PATH"
arduino-cli core install arduino:avr
arduino-cli lib install Servo
arduino-cli compile --fqbn arduino:avr:mega arduino/inmoov_robot_controller
arduino-cli upload -p /dev/ttyUSB0 --fqbn arduino:avr:mega arduino/inmoov_robot_controller
```

Ejemplo de comando serial directo:

```text
ROBOT JOINTS 6:90 17:40
```

## Ejecucion

```bash
cd /home/felipe/rpi_voice_assistant
python3 -m pip install -r requirements.txt
python3 main.py
```

## Pruebas

```bash
cd /home/felipe/rpi_voice_assistant
python3 -m unittest discover -s tests -v
```
