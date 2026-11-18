# Pantalla Extra

Usa tu iPad como segunda pantalla de tu laptop Windows **por cable USB-C**, sin Wi-Fi.

```
Windows: pantalla virtual → FFmpeg (chip de video de la laptop) → pantalla.py
   → cable USB-C (servicio de Apple, usbmux) → iPad: app Pantalla Extra (decodifica por hardware)
```

- Video H.264 a 60 fps, cuadro clave cada segundo (si algo falla se recupera en menos de 1 s).
- El cuadro se envía apenas está completo y el iPad lo muestra sin cola de reproducción.
- La pantalla virtual es un monitor real para Windows: arrastras ventanas hacia el iPad con el mouse de la laptop.

## Lo que necesitas (una sola vez)

**En la laptop (Windows 10/11):**

1. **Python 3**: `winget install Python.Python.3.12`
2. **FFmpeg 6.1 o superior**: `winget install Gyan.FFmpeg`
3. **Apple Devices** (Microsoft Store) o iTunes: instala el driver USB del iPad.
4. **Sideloadly** (sideloadly.io): instala la app en el iPad con tu Apple ID gratis.
5. **Virtual Display Driver** (github.com/VirtualDrivers/Virtual-Display-Driver, sección Releases):
   crea una pantalla extra "fantasma" en Windows. En su configuración elige la resolución de tu iPad
   (ver tabla abajo) y quita las demás.

**Resolución según tu iPad (horizontal).** El iPad con chip A16 (11.ª generación) usa **2360 × 1640**.

| iPad | Resolución |
|---|---|
| iPad 10.ª / 11.ª gen, iPad Air 11" | 2360 × 1640 |
| iPad Air 13" | 2732 × 2048 |
| iPad Pro 11" | 2388 × 1668 (M4: 2420 × 1668) |
| iPad Pro 12.9" / 13" | 2732 × 2048 (M4: 2752 × 2064) |
| iPad mini 6 / 7 | 2266 × 1488 |

Si notas retraso o la laptop se calienta, usa la mitad (por ejemplo 1180 × 820): se ve un poco menos nítido y va más fluido.

## Instalar la app en el iPad (gratis, se renueva cada 7 días)

1. Descarga `PantallaExtra.ipa` desde la pestaña **Actions** del repositorio (último build verde → Artifacts).
2. Conecta el iPad por cable, abre Sideloadly, arrastra el `.ipa`, escribe tu Apple ID y pulsa **Start**.
3. En el iPad: **Ajustes → General → VPN y gestión de dispositivos** → confía en tu Apple ID.
4. En el iPad: **Ajustes → Privacidad y seguridad → Modo de desarrollador** → activar → reiniciar.

Con un Apple ID gratis la app deja de abrir a los 7 días: vuelve a pasarla con Sideloadly (toma 1 minuto;
Sideloadly puede renovarla solo si dejas activada su opción de auto-refresh).

## Usarla

1. Conecta el iPad por cable y abre **Pantalla Extra** en el iPad.
2. En la laptop, doble clic en `windows/iniciar.bat`.
3. En Windows → **Configuración → Pantalla**, coloca la pantalla virtual al lado donde está el iPad.

Opciones útiles (`iniciar.bat --opción`):

| Opción | Para qué |
|---|---|
| `--pantalla 1` | Qué pantalla enviar (0 = la de la laptop, 1 = la virtual). Por defecto 1. |
| `--fps 30` | Menos carga si la laptop es lenta. |
| `--bitrate 12000000` | Menos datos (12 Mbps) si ves cortes. |
| `--codificador qsv` | Forzar el chip: `qsv` (Intel), `amf` (AMD), `nvenc` (NVIDIA), `mf`, `x264` (CPU). |
| `--pantalla prueba` | Envía una imagen de prueba para verificar el cable y la app. |
| `--listar` | Ver si Windows detecta el iPad por USB. |

## Problemas comunes

- **"No encuentro el servicio de Apple"**: instala Apple Devices o iTunes y desbloquea el iPad.
- **"El iPad rechazó la conexión"**: abre la app Pantalla Extra en el iPad y déjala en primer plano.
- **Pantalla negra**: prueba `--pantalla 0`; si así funciona, el número de la pantalla virtual es otro (2, 3…).
- **La app no abre**: pasaron los 7 días; vuelve a instalarla con Sideloadly.

## Próximas mejoras

- Tocar la pantalla del iPad para hacer clic en Windows.
- Ajustar resolución y calidad desde la app del iPad.
- Medidor de retraso en pantalla.
