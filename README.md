# Hidromotic para Home Assistant

Esta integración permite controlar desde Home Assistant las computadoras de riego
CHI Smart y CHI Smart Mini de [Hidromotic](https://www.hidromotic.com.ar).

Antes de agregar la integración, configurá el equipo y sus salidas desde el
[portal de Hidromotic](https://sites.google.com/hidromotic.com.ar/chismart/inicio).
Home Assistant mostrará las entidades correspondientes a los recursos
configurados en el CHI.

## Instalación mediante HACS

1. Verificá que [HACS](https://www.hacs.xyz/) esté instalado y configurado en Home
   Assistant.
2. Abrí **HACS** y entrá en **Integraciones**.
3. Buscá **Hidromotic** en el catálogo de integraciones de HACS.
4. Abrí la integración y seleccioná **Descargar**.
5. Reiniciá Home Assistant.

Para actualizarla, abrí **HACS > Integraciones**, buscá **Hidromotic** e
instalá la actualización disponible. Reiniciá Home Assistant para aplicar los
cambios.

## Configuración

1. En Home Assistant, abrí **Ajustes > Dispositivos y servicios**.
2. Seleccioná **Añadir integración** y buscá **Hidromotic**.
3. En el campo **Host**, ingresá la dirección IP o el nombre de host del CHI
   en la red local. Podés encontrar la IP en la lista de dispositivos/DHCP del
   router o en la configuración de red del equipo. No incluyas `http://` ni
   `https://`.
4. Confirmá para finalizar. El dispositivo debe estar encendido y accesible
   desde Home Assistant durante la configuración.

Se recomienda asignar una IP fija al CHI o configurar una reserva DHCP en el
router, para que la dirección no cambie.

## Uso

Las entidades disponibles dependen de la configuración del CHI. La integración
puede crear:

- **Interruptores** para zonas de riego, programas, tanques, piscinas, mangueras
  e HidroCiclón, además del control general de riego automático.
- **Selectores de modo** para elegir entre manual y automático en cada tanque
  que tenga un flotante configurado.
- **Controles numéricos** para ajustar en minutos la duración de las zonas,
  piscinas y tanques.
- **Sensores** de estado de bomba, nivel de tanque, entradas físicas y datos de
  diagnóstico y conectividad.
- **Botón de diagnóstico** para reiniciar el dispositivo.

Podés usar los interruptores y controles desde la página del dispositivo,
agregarlos a un panel o incorporarlos en automatizaciones y escenas. Los cambios
de duración se envían al CHI; las entidades reflejan los recursos configurados
en el equipo.

Tené en cuenta que activar o desactivar una salida puede poner en marcha o
detener equipos y el riego físico. Verificá la instalación y las condiciones de
riego antes de automatizar esos controles. Usá el botón de reinicio únicamente
cuando necesites reiniciar el CHI.

## Registros de depuración

Para obtener registros detallados de la integración, agregá esta configuración
a `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.hidromotic: debug
```

Si ya tenés una sección `logger:`, agregá `custom_components.hidromotic: debug`
dentro de `logs:` en lugar de crear una segunda sección. Después, reiniciá Home
Assistant. Los mensajes de la integración aparecerán en **Ajustes > Sistema >
Registros**; buscá `custom_components.hidromotic`.

El nivel DEBUG incluye detalles del protocolo y tramas binarias para facilitar
el diagnóstico. Las credenciales de campos reconocidos se ocultan, pero revisá
y redactá los registros antes de compartirlos.

## Ayuda y créditos

Para aprender a configurar la computadora de riego, consultá el
[portal de Hidromotic](https://sites.google.com/hidromotic.com.ar/chismart/inicio).
Si encontrás un problema con la integración, abrí un
[issue en GitHub](https://github.com/demonio669/hidromotic/issues).

Este trabajo se basa en el [trabajo de Juan Manuel](https://github.com/bulju) y
en el [pull request de Home Assistant Core](https://github.com/home-assistant/core/pull/160615).
