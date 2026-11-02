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
3. Abrí el menú de opciones (tres puntos) y seleccioná **Repositorios
   personalizados**.
4. Agregá `https://github.com/demonio669/hidromotic` y elegí **Integración**
   como categoría.
5. Buscá **Hidromotic** en HACS y seleccioná **Descargar**.
6. Reiniciá Home Assistant.

Para actualizarla, buscá Hidromotic en HACS, instalá la actualización disponible
y reiniciá Home Assistant.

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
- **Controles numéricos** para ajustar en minutos la duración de las zonas y el
  tiempo de llenado de piscinas.
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

## Ayuda y créditos

Para aprender a configurar la computadora de riego, consultá el
[portal de Hidromotic](https://sites.google.com/hidromotic.com.ar/chismart/inicio).
Si encontrás un problema con la integración, abrí un
[issue en GitHub](https://github.com/demonio669/hidromotic/issues).

Este trabajo se basa en el [trabajo de Juan Manuel](https://github.com/bulju) y
en el [pull request de Home Assistant Core](https://github.com/home-assistant/core/pull/160615).
