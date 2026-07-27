![](./assets/banner.jpg)

<h1 align="center">Open-LLM-VTuber</h1>
<h3 align="center">

[![GitHub release](https://img.shields.io/github/v/release/Open-LLM-VTuber/Open-LLM-VTuber)](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/releases) 
[![license](https://img.shields.io/github/license/Open-LLM-VTuber/Open-LLM-VTuber)](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/blob/master/LICENSE) 
[![CodeQL](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/actions/workflows/codeql.yml/badge.svg)](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/actions/workflows/codeql.yml)
[![Ruff](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/actions/workflows/ruff.yml/badge.svg)](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/actions/workflows/ruff.yml)
[![Docker](https://img.shields.io/badge/Open-LLM-VTuber%2FOpen--LLM--VTuber-%25230db7ed.svg?logo=docker&logoColor=blue&labelColor=white&color=blue)](https://hub.docker.com/r/Open-LLM-VTuber/open-llm-vtuber) 
[![QQ User Group](https://img.shields.io/badge/QQ_User_Group-792615362-white?style=flat&logo=qq&logoColor=white)](https://qm.qq.com/q/ngvNUQpuKI)
[![Static Badge](https://img.shields.io/badge/Join%20Chat-Zulip?style=flat&logo=zulip&label=Zulip(dev-community)&color=blue&link=https%3A%2F%2Folv.zulipchat.com)](https://olv.zulipchat.com)

> **📢 Desarrollo de v2.0**: Nos estamos centrando en Open-LLM-VTuber v2.0 — una reescritura completa del código base. La v2.0 se encuentra actualmente en su fase inicial de discusión y planificación. Les pedimos amablemente que se abstengan de abrir nuevos issues o pull requests para solicitudes de funciones en la v1. Para participar en las discusiones de la v2 o contribuir, únase a nuestra comunidad de desarrolladores en [Zulip](https://olv.zulipchat.com). Los horarios de las reuniones semanales se anunciarán en Zulip. Continuaremos corrigiendo errores de la v1 y procesando los pull requests existentes.

[![BuyMeACoffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://www.buymeacoffee.com/yi.ting)
[![](https://dcbadge.limes.pink/api/server/3UDA8YFDXx)](https://discord.gg/3UDA8YFDXx)

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/Open-LLM-VTuber/Open-LLM-VTuber)

README EN INGLÉS | [README 中文](./README.CN.md) | [README 한국어](./README.KR.md) | [README 日本語](./README.JP.md)

[Documentación](https://open-llm-vtuber.github.io/docs/quick-start) | [![Roadmap](https://img.shields.io/badge/Roadmap-GitHub_Project-yellow)](https://github.com/orgs/Open-LLM-VTuber/projects/2)

<a href="https://trendshift.io/repositories/12358" target="_blank"><img src="https://trendshift.io/api/badge/repositories/12358" alt="Open-LLM-VTuber%2FOpen-LLM-VTuber | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>

</h3>


> Documento de Problemas Comunes (en chino): https://docs.qq.com/pdf/DTFZGQXdTUXhIYWRq
>
> Encuesta de Usuario: https://forms.gle/w6Y6PiHTZr1nzbtWA
>
> 调查问卷(中文): https://wj.qq.com/s2/16150415/f50a/


> :warning: Este proyecto se encuentra en sus etapas iniciales y está bajo **desarrollo activo**.

> :warning: Si desea ejecutar el servidor de forma remota y acceder a él desde una máquina diferente (por ejemplo, ejecutar el servidor en su computadora y acceder desde su teléfono), deberá configurar `https`, ya que el micrófono en el front-end solo se iniciará en un contexto seguro (es decir, https o localhost). Consulte la [Documentación Web de MDN](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia). Por lo tanto, debe configurar https con un proxy inverso para acceder a la página en una máquina remota (que no sea localhost).


## ⭐️ ¿Qué es este proyecto?


**Open-LLM-VTuber** es un **compañero de IA interactivo por voz** único que no solo admite **conversaciones de voz en tiempo real** y **percepción visual**, sino que también cuenta con un animado **avatar Live2D**. ¡Todas las funcionalidades pueden ejecutarse completamente offline en su computadora!

Puede tratarlo como su compañero de IA personal; ya sea que desee una `novia virtual`, `novio`, `mascota linda` o cualquier otro personaje, puede cumplir con sus expectativas. El proyecto es totalmente compatible con `Windows`, `macOS` y `Linux`, y ofrece dos modos de uso: versión web y cliente de escritorio (con soporte especial para el **modo de mascota de escritorio con fondo transparente**, permitiendo que el compañero de IA lo acompañe en cualquier lugar de su pantalla).

Aunque la función de memoria a largo plazo ha sido eliminada temporalmente (volverá pronto), gracias al almacenamiento persistente de los registros de chat, siempre puede continuar sus conversaciones anteriores sin perder ningún momento interactivo precioso.

En cuanto al soporte de backend, hemos integrado una amplia variedad de soluciones de inferencia de LLM, texto a voz (TTS) y reconocimiento de voz (ASR). Si desea personalizar su compañero de IA, puede consultar la [Guía de Personalización de Personajes](https://open-llm-vtuber.github.io/docs/user-guide/live2d) para personalizar la apariencia y la personalidad de su compañero.

La razón por la que se llama `Open-LLM-Vtuber` en lugar de `Open-LLM-Companion` o `Open-LLM-Waifu` es que el objetivo inicial del proyecto era utilizar soluciones de código abierto que pudieran ejecutarse offline en plataformas distintas a Windows para recrear a la AI Vtuber de código cerrado `neuro-sama`.

### 👀 Demo
| ![](assets/i1.jpg) | ![](assets/i2.jpg) |
|:---:|:---:|
| ![](assets/i3.jpg) | ![](assets/i4.jpg) |


## ✨ Características y Aspectos Destacados

- 🖥️ **Soporte multiplataforma**: Compatibilidad perfecta con macOS, Linux y Windows. Soportamos GPUs NVIDIA y no NVIDIA, con opciones para ejecutar en CPU o usar APIs en la nube para tareas intensivas en recursos. Algunos componentes admiten aceleración por GPU en macOS.

- 🔒 **Soporte de modo offline**: Ejecución completamente offline utilizando modelos locales; no se requiere internet. Sus conversaciones permanecen en su dispositivo, garantizando la privacidad y la seguridad.

- 💻 **Clientes web y de escritorio atractivos y potentes**: Ofrece modos de uso tanto en versión web como en cliente de escritorio, con ricas funciones interactivas y ajustes de personalización. El cliente de escritorio puede alternar libremente entre el modo ventana y el modo mascota de escritorio, permitiendo que el compañero de IA esté a su lado en todo momento.

- 🎯 **Funciones de interacción avanzadas**:
  - 👁️ Percepción visual, con soporte para cámara, grabación de pantalla y capturas, permitiendo que su compañero de IA lo vea a usted y a su pantalla.
  - 🎤 Interrupción de voz sin auriculares (la IA no escuchará su propia voz).
  - 🫱 Retroalimentación táctil, interactúe con su compañero de IA a través de clics o arrastres.
  - 😊 Expresiones Live2D, configure el mapeo de emociones para controlar las expresiones del modelo desde el backend.
  - 🐱 Modo mascota, con soporte para fondo transparente, siempre al frente y clics transparentes: arrastre a su compañero de IA a cualquier lugar de la pantalla.
  - 💭 Visualización de los pensamientos internos de la IA, permitiéndole ver las expresiones, pensamientos y acciones de la IA sin que sean pronunciados.
  - 🗣️ Función de habla proactiva de la IA.
  - 💾 Persistencia de registros de chat, cambie a conversaciones anteriores en cualquier momento.
  - 🌍 Soporte de traducción TTS (por ejemplo, chatear en español mientras la IA utiliza una voz japonesa).

- 🧠 **Amplio soporte de modelos**:
  - 🤖 Modelos de Lenguaje Extensos (LLM): Ollama, OpenAI (y cualquier API compatible con OpenAI), Gemini, Claude, Mistral, DeepSeek, Zhipu AI, GGUF, LM Studio, vLLM, etc.
  - 🎙️ Reconocimiento Automático de Voz (ASR): sherpa-onnx, FunASR, Faster-Whisper, Whisper.cpp, Whisper, Groq Whisper, Azure ASR, etc.
  - 🔊 Texto a Voz (TTS): sherpa-onnx, pyttsx3, MeloTTS, Coqui-TTS, GPTSoVITS, Bark, CosyVoice, Edge TTS, Fish Audio, Azure TTS, etc.

- 🔧 **Altamente personalizable**:
  - ⚙️ **Configuración simple de módulos**: Cambie varios módulos funcionales mediante modificaciones sencillas en el archivo de configuración, sin necesidad de profundizar en el código.
  - 🎨 **Personalización de personajes**: Importe modelos Live2D personalizados para darle a su compañero de IA una apariencia única. Moldee la personalidad de su compañero modificando el Prompt. Realice clonación de voz para darle la voz que desee.
  - 🧩 **Implementación flexible de Agentes**: Hereda e implementa la interfaz de Agent para integrar cualquier arquitectura de Agente, como HumeAI EVI, OpenAI Her, Mem0, etc.
  - 🔌 **Buena extensibilidad**: El diseño modular le permite agregar fácilmente sus propias implementaciones de LLM, ASR, TTS y otros módulos, extendiendo nuevas funciones en cualquier momento.


## 👥 Opiniones de Usuarios
> Gracias al desarrollador por abrir el código y compartir la novia para que todos la usen.
> 
> Esta novia ha sido utilizada más de 100,000 veces.


## 🚀 Inicio Rápido

Por favor, consulte la sección de [Inicio Rápido](https://open-llm-vtuber.github.io/docs/quick-start) en nuestra documentación para la instalación.


## ☝ Actualización
> :warning: `v1.0.0` incluye cambios disruptivos y requiere un nuevo despliegue. *Es posible* que aún pueda actualizar mediante el método indicado a continuación, pero el archivo `conf.yaml` es incompatible y la mayoría de las dependencias deben reinstalarse con `uv`. Para aquellos que provengan de versiones anteriores a `v1.0.0`, recomiendo desplegar este proyecto nuevamente siguiendo la [guía de despliegue más reciente](https://open-llm-vtuber.github.io/docs/quick-start).

Por favor, use `uv run update.py` para actualizar si instaló cualquier versión posterior a `v1.0.0`.

## 😢 Desinstalación
La mayoría de los archivos, incluyendo las dependencias de Python y los modelos, se almacenan en la carpeta del proyecto.

Sin embargo, los modelos descargados a través de ModelScope o Hugging Face también pueden estar en `MODELSCOPE_CACHE` o `HF_HOME`. Aunque nuestro objetivo es mantenerlos en el directorio `models` del proyecto, es recomendable verificarlo.

Revise la guía de instalación para cualquier herramienta adicional que ya no necesite, como `uv`, `ffmpeg` o `deeplx`.

## 🤗 ¿Quieres contribuir?
Consulte la [guía de desarrollo](https://docs.llmvtuber.com/docs/development-guide/overview).


# 🎉🎉🎉 Proyectos Relacionados

[ylxmf2005/LLM-Live2D-Desktop-Assitant](https://github.com/ylxmf2005/LLM-Live2D-Desktop-Assitant)
- ¡Su asistente de escritorio Live2D impulsado por LLM! Disponible tanto para Windows como para MacOS, detecta su pantalla, recupera el contenido del portapapeles y responde a comandos de voz con una voz única. Cuenta con activación por voz, capacidades de canto y control total de la computadora para una interacción fluida con su personaje favorito.


## 📜 Licencias de Terceros

### Aviso sobre Modelos de Muestra de Live2D

Este proyecto incluye modelos de muestra de Live2D proporcionados por Live2D Inc. Estos activos están licenciados por separado bajo el Acuerdo de Licencia de Material Gratuito de Live2D y los Términos de Uso de los Datos de Muestra de Live2D Cubism. No están cubiertos por la licencia MIT de este proyecto.

Este contenido utiliza datos de muestra propiedad y propiedad intelectual de Live2D Inc. Los datos de muestra se utilizan de acuerdo con los términos y condiciones establecidos por Live2D Inc. (Consulte el [Acuerdo de Licencia de Material Gratuito de Live2D](https://www.live2d.jp/en/terms/live2d-free-material-license-agreement/) y los [Términos de Uso](https://www.live2d.com/eula/live2d-sample-model-terms_en.html)).

Nota: Para uso comercial, especialmente por parte de empresas medianas o grandes, el uso de estos modelos de muestra de Live2D puede estar sujeto a requisitos de licencia adicionales. Si planea utilizar este proyecto comercialmente, asegúrese de tener los permisos adecuados de Live2D Inc., o utilice versiones del proyecto sin estos modelos.


## Colaboradores
Gracias a nuestros colaboradores y mantenedores por hacer posible este proyecto.

<a href="https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=Open-LLM-VTuber/Open-LLM-VTuber" />
</a>


## Historial de Estrellas

[![Star History Chart](https://api.star-history.com/svg?repos=Open-LLM-VTuber/open-llm-vtuber&type=Date)](https://star-history.com/#Open-LLM-VTuber/open-llm-vtuber&Date)
