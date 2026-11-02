// "use strict";
var pvm = {},         // menu management
pve = {scanwifi : 0}, // esp management
pv = {}, pv1 = {},    // pic management
ur = 'Última Recepción',

id2hex = id => {
  switch (id) {
    case 10: return 'A';
    case 11: return 'B';
    case 12: return 'C';
    case 13: return 'D';
  }
  return id;
};

hex2int = h => {
  switch (h) {
  case 'A': return 10;
  case 'B': return 11;
  case 'C': return 12;
  }
  return h;
};

hexU = v => ('0' + v.toString(16).toUpperCase()).slice(-2);

process = () => {
  let m, ii, b = pv.b, decoder = new TextDecoder(); 
  let max_salidas;
  // '{', len lo, len hi, Command, data, ..., crc lo, hi, '}'
  //  -3,     -2,     -1,       0,    1, ...
  if (b.length == 1) return console.log(b[0].toString(16));
  
  // Full or running data
  switch (decoder.decode(b.slice(0, 1))) {
  case 'r': return console.log('rcon', Array.from(b).map(i=>('0' + i.toString(16)).slice(-2)).join(' '));
  case 'C': // full data LSB
  /* C, mini?, version(2), conf version(2), pic id(2), fecha(8), LED(2), boton(12), Entrada(17), Bomba(3)*/
  // '{', len lo, len hi, Command, name/tipo, ver hi, lo, config hi, lo, pic id hi, lo, 'f', 7byte, ..., crc lo, hi, '}'
  //  -3,     -2,     -1,       0,         1,      2,  3,         4,  5,         6,  7,   8, 9-15, ...
    ii = (b[4] | (b[5] << 8));
    if (typeof pv.config_counter === 'undefined') pv.config_counter = ii;
    if (pv.config_counter != ii) rl_pic();

    pv.IsMini = (b[1] == 77); // 'M' = 77
    max_salidas = pv.IsMini ? 6 : 12;
    pv.pic_name = 'CHI Smart' + (pv.IsMini ? ' Mini' : '');
    cst.children[0].innerHTML = pv.pic_name;
    pv.pic_version = (b[2] | (b[3] << 8));
    pv.pic_id = '0x' + ('0' + b[6].toString(16).toUpperCase()).slice(-2);
    pv.pic_rev = b[7];
    // 2018-09-11 12:00:49
    // DATEH = 0x1809; // Year/Month
    // DATEL = 0x1102; // Date/Wday
    // TIMEH = 0x1200; // hours/minutes
    // TIMEL = 0x4900; // seconds
    BCDToHex = v => ((((v & 0xF0) >> 4) * 10) + (v & 0x0F));
    if (!pv.f) pv.f = {};
    m = pv.f;
    m.b = b.slice(9, 16);
    if (!m.tzo) m.tzo = new Date().getTimezoneOffset();
    // uninit value 0, 1, 1, 6, 0, 0, 19
    m.utc = Date.UTC(2000 + BCDToHex(m.b[1]), BCDToHex(m.b[0]), BCDToHex(m.b[3]), BCDToHex(m.b[5]), BCDToHex(m.b[4]) + m.tzo, BCDToHex(m.b[6]));
    m.diff = Date.now() - m.utc;
    m.f = (new Date(m.utc));
    if (fecha.innerHTML == '') fecha.innerHTML = ff(new Date(pv.f.utc));
    pv.L = [];
    delete pv.H;
    delete pv.R;
    for (let i = 16; i < b.length; i++) {
      m = decoder.decode(b.slice(i, i + 1));
      switch(m) {
      case 'E': // Entradas, tipo, invert, actual, estado, count/falla
        pv.E = [];
        for (let j = 0; j < 4; j++) {
          pv.E[j] = { 
            id :j,
            tipo : b[++i],
            invert : b[++i],
            actual : b[++i],
            estado : b[++i],
            l : ''
          };
          // FOR SRV START
          if (pv.pic_version > 710) 
          // FOR SRV END
            pv.E[j].contar = b[++i];
        }
        break;
    
      case 'B':
        pv.B = {
          estado : b[++i],
          pausa_externa : b[++i],
          marcha : b[++i] | (b[++i] << 8) | (b[++i] << 16) | (b[++i] << 24)
        };
        // FOR SRV START
        if (pv.pic_version > 360) { // tiempo en segundos
        // FOR SRV END
          pv.B.t0_offduración = (b[++i] | (b[++i] << 8));
          pv.B.t1_onDelay = b[++i] | (b[++i] << 8);
          pv.B.t2_desactivando = b[++i] | (b[++i] << 8);
          pv.B.t3_pozoseco = b[++i] | (b[++i] << 8);
        // FOR SRV START          
        }
        if (pv.pic_version > 370) {
        // FOR SRV END
          // pv.B.pozoseco_auto_recover = b[++i];
          pv.B.t4_pozoseco_auto_recover = b[++i] | (b[++i] << 8);
        // FOR SRV START          
        }
        // FOR SRV END
        break;

      case 'H':
        if (typeof pv.H === 'undefined') pv.H = [];
        ii = b[i + 1];
        pv.H[ii] = {
          id : ii, 
          estado : b[i + 2],
          active_zona : b[i + 3],
          modo : b[i + 4],
          duración : b[i + 5] | b[i + 6] << 8 | b[i + 7] << 16 | b[i + 8] << 24,
          accesorios : b[i + 9],
          habilitado : b[i + 10],
          horas : ((b[i + 11] >> 4) * 10) + (b[i + 11] & 0x0F),
          minutos : ((b[i + 12] >> 4) * 10) + (b[i + 12] & 0x0F),
          paridad : b[i + 13],
          dias_semana : b[i + 14],
          zonas : [],
          l : ''
        };
        for (let j = 0; j < max_salidas; j++) pv.H[ii].zonas[j] = (b[i + (j * 2) + 15] | (b[i + (j * 2) + 16] << 8));
        i += (pv.IsMini ? 26 : 38) + 1;
        if (b[i]) pv.H[ii].l = decoder.decode(b.slice(i + 1, i + 1 + b[i]));
        i += b[i];


        break;

      case 'L':
        ii = b[++i];
        pv.L[ii] = {
          id : ii,
          tipo : hexU(b[++i]),
          modo : b[++i]
        };
        if (ii == 0) pv.L[ii].duración = b[++i] | (b[++i] << 8);
        break;
        
      case 'R':
        pv.R = {
          modo : b[++i],
          active_horario : b[++i],
          sensorDeLluvia : b[++i]
        };
        break;

      case 'S': // Salidas, tipo, bomba, duracion(4), actual/estado, tanque modo
        pv.S = [];
        pv.SS = {};
        delete pv.Ciclon; delete pv.M; delete pv.T; delete pv.Z; delete pv.P;
        for (let j = 0; j < max_salidas; j++) {    
          let tipo = b[i + 1];
          pv.SS[tipo] = j;
          pv.S[j] = {
            id : j,
            tipo : hexU(tipo),
            bomba : b[i + 2],
            duración : (b[i + 3] | (b[i + 4] << 8)), /* | (b[i + 5] << 16) | (b[i + 6] << 24)),*/
            estado : b[i + 5],
            l : ''
          };
          i += 6;
          if (b[i] != 0) pv[m][j].l = decoder.decode(b.slice(i + 1, i + 1 + b[i]));
          i += b[i];  

          if (pv.S[j].estado == 7) {
            // switch (tipo & 0xF0) {
            //   case 0x20: i += 3; break;
            //   case 0x60: i += 6; break;
            // }
            continue; // salida deshabilitado
          }
          let ii = (tipo & 0x0F) - 1;
          switch (tipo & 0xF0) {
          case 0x60:
            // FOR SRV START
            if (pv.pic_version > 360) {
            // FOR SRV END
              pv.Ciclon = {
                s : pv.S[j],
                modo_ante_tareas : b[++i],
                modo_fin_de_tareas : b[++i],
                modo_tiempo : b[++i],
                d_ante_tareas : b[++i] | (b[++i] << 8),
                d_fin_de_tareas : b[++i],
                bomba_marcha_duracion : b[++i] | (b[++i] << 8),
                proximo_ciclon : b[++i] | (b[++i] << 8),
              };
            // FOR SRV START
            } else {
              pv.Ciclon = {
                s : pv.S[j],
                modo_fin_de_tareas : b[++i],
                modo_tiempo : b[++i],
                bomba_marcha_duracion : b[++i] | (b[++i] << 8),
                proximo_ciclon : b[++i] | (b[++i] << 8),
              };
            }
            // FOR SRV END
            pv.S[j].name = 'Ciclon';
            break;

          case 0x10:
            if (typeof pv.M === 'undefined') pv.M = [];
            pv.M[ii] = { id : ii, s : pv[m][j] };
            pv[m][j].name = 'Manguera';
            break;
      
          case 0x20:
            if (typeof pv.T === 'undefined') pv.T = [];
            pv.T[ii] = {
              id : ii,
              s : pv.S[j],
              modo : b[i + 1],
              nivel : b[i + 2],
              tipo_flotante : b[i + 3],
            }
            i += 3;
            pv.S[j].name = 'Tanque';
            break;
      
          case 0x40:
            if (typeof pv.Z === 'undefined') pv.Z = [];
            pv.Z[ii] = { id : ii, s : pv[m][j] };
            pv.S[j].name = 'Zona';
            break;
        
          case 0x50:
            if (typeof pv.P === 'undefined') pv.P = [];
            pv.P[ii] = { id : ii, s : pv[m][j] };
            pv.S[j].name = 'Piscina';
            break;
          }
        }
        break;

      // batería en %
      case 'b': pv['Batería'] = b[++i] | (b[++i] << 8);break;

      case 'u': i++; pv['U1 reset Count'] = b[++i] | (b[++i] << 8); break;

      case 'c': pv['ESP reset Count'] = b[++i] | (b[++i] << 8); break;
        
      // led
      case 'l': pv.LED = { enabled : b[++i] }; break;

      // boton
      case 'k':
        pv.Boton = { enabled : b[++i], f : [] };
        for (let j = 0; j < 10; j++) pv.Boton.f[j] = hexU(b[++i]);
        // FOR SRV START
        if (pv.pic_version > 400) 
        // FOR SRV END
          pv.Boton.b_contar = b[++i] | (b[++i] << 8);
        // FOR SRV START
        if (pv.pic_version > 551) 
        // FOR SRV END
          pv.Boton.falla = b[++i];
        break;
      }
    }
    let nn = pp => {if (pp && (pp.flat().length > 1)) pp.forEach(m => m.s.name += ' ' + hex2int(m.s.tipo[1]))};
    nn(pv.M); nn(pv.T); nn(pv.Z); nn(pv.P);
    showMain();
    break;

  case 'D': // running data
    if (typeof pv.pic_version === 'undefined') return p('#@C;');
  /* D, mini?, version(2), conf version(2), E, id, estado, B, estado, pausa externa, S, ..., L, ...*/
    if (typeof pv.L !== 'undefined') delete pv.L;
    // b.forEach((v,i) => {
    //   console.log(i, v.toString(16), String.fromCharCode(v));
    // });
    for (let i = 6; i < b.length; i++) {
      m = decoder.decode(b.slice(i, i + 1));
      console.log(b.length, i, m, b[i + 1].toString(16));
      switch(m) {
        case 'k': pv.Boton.b_contar = b[++i] | (b[++i] << 8); break;

        case 'E': // Entradas, tipo, estado
          pv.E[b[i + 1]].estado = b[i + 2];
          // FOR SRV START
          if (pv.pic_version > 710) {
          // FOR SRV END
            pv.E[b[i + 1]].contar = b[i + 3];
            i++;
          // FOR SRV START
          }
          // FOR SRV END
          i += 2;
          break;
      
        case 'B':
          pv.B.estado = b[++i];
          pv.B.pausa_externa = b[++i];
          pv.B.marcha = b[++i] | (b[++i] << 8) | (b[++i] << 16) | (b[++i] << 24);
          break;

        case 'H':
          if (typeof pv.H !== 'undefined') {
            pv.H[b[i + 1]].estado = b[i + 2];
            pv.H[b[i + 1]].active_zona = b[i + 3];
            pv.H[b[i + 1]].modo = b[i + 4];
            pv.H[b[i + 1]].duración = (b[i + 5] | (b[i + 6] << 8) | (b[i + 7] << 16) | (b[i + 8] << 24));
          }
          i += 8;
          break;

        case 'R':
          if (typeof pv.R !== 'undefined') {
            pv.R.active_horario = b[i + 1];
            pv.R.sensorDeLluvia = b[i + 2];
          }
          i += 2;
          break;

        case 'L':
          if (typeof pv.L === 'undefined') pv.L = [];
          let ii = b[i + 1];
          pv.L[ii] = {
            id : ii,
            tipo : hexU(b[i + 2]),
            modo : b[i + 3]
          };
          if (ii == 0) {
            pv.L[ii].duración = (b[i + 4] | b[i + 5] << 8);
            i += 5;
          } else i += 3;
          break;

        case 'S': // Salidas, estado, duracion(4), tanque nivel
          let id = pv.SS[b[++i]];
          try {
            pv.S[id].estado = b[++i];
          } catch (e) {
            console.log('err', e);
          }
          let tipo = pv[m][id].tipo;
          switch (tipo[0]) {
            case '2':
              if (pv.T[tipo[1] - 1]) pv.T[tipo[1] - 1].nivel = b[++i];
              break;

            case '6':
              if (typeof pv.Ciclon !== 'undefined') {
                if (pv.Ciclon.modo_tiempo) pv.Ciclon.proximo_ciclon = b[++i] | (b[++i] << 8);
              }
              break;
          }
          break;

        // boton
        case 'k': pv.Boton.estado = b[++i]; break;

        // batería
        case 'b': pv['Batería'] = (b[++i] | (b[++i] << 8)); break;

        case 'u': i++; pv['UART reset Count'] = b[++i] | (b[++i] << 8); break;
      }
    }
    break;
  }
};

process_binary = () => {
  process();
  try {
    if (pv.b.length == 1) console.log(pvm, pv);
  } catch (e) { console.log(pv.b) }

  switch (pvm.menu) {
    case 'Manual':
      if (mainTab.style.display == 'none') return showMain();
      menu(pvm.menu);
      break;

    case 'Ajustes':
      window['u' + pvm.menuAjustes]();
      // if (typeof pv.S === 'undefined') break;
      // if (typeof pvm.menuAjustes !== 'undefined') window['u' + pvm.menuAjustes]();
      // else showAjustes();

      // if (!pv1.m) delete pv1.R; delete pv1.H; delete pv1.Z; delete pv1.T; delete pv1.P; delete pv1.Ciclon;

      // switch (pvm.menuAjustes) {
      //   case 'Riego': 
      //   case 'Zona': if (typeof pv.Z !== 'undefined') return window['u' + pvm.menuAjustes](); break;
      //   case 'Tanque': if (typeof pv.T !== 'undefined') return window['u' + pvm.menuAjustes](); break;
      //   case 'Piscina': if (typeof pv.P !== 'undefined') return window['u' + pvm.menuAjustes](); break;
      //   case 'Ciclon': if (typeof pv.Ciclon !== 'undefined') return window['u' + pvm.menuAjustes](); break;
      // }
      // delete pvm.menuAjustes;
      // if (pv.T || pv.Z || pv.P || pv.Ciclon) return showAjustes();
      // delete pvm.menu;
      // menu('Manual');
      break;

    case 'Sistema':
      switch (pvm.menuSistema) {
        case 'Wifi': showWifi(); break;
        case 'Boton':
        case 'Salidas': 
        case 'Entradas': window['u' + pvm.menuSistema]();
      }
      break;
    case 'Info': showInfo(); break;
  }
};

ws_msg = e => {
  pv.c_msg++;
  pv[ur] = ff(Date.now());
  // if (e.data) console.log(e, e.data);
  if (pv.hock) console.log(pv.c_msg, pv[ur], typeof(e.data), e);
  if (e.data instanceof ArrayBuffer){
    if (typeof pv.b === 'undefined') pvm.menu = 'Manual';
    pv.b = new Uint8Array((new DataView(e.data)).buffer);
    // if (pv.b.length <= 5) { return console.log(pv.b); }
    if (mainContent.innerHTML.indexOf('Clave') == 0) return;
    process_binary();
    return;
  }
  let j;
  try { j = JSON.parse(e.data)} catch (err) { return console.log( '---', e, e.data, err)}
  if (j.error) {
    if (j.error.message == 'wifi scan failed') {
      pve.scanwifi = 2;
      if ((pvm.menu == 'Sistema') && (pvm.menuSistema == 'Wifi')) showWifi();
      _showModal('Wifi Error', j.error.message);
      return;
    }
    _showModal('Error', j.error.message);
    rl_pic();
    p('#@C;');
    return;
  }
  if (j.result) {
    if (typeof j.result === 'string') {
      if (j.result == 'chi pic reset') {
        rl_pic();
        setTimeout(p('#@C;'), 2000);
        switch (pvm.menu) {
          case 'Manual':
          case 'Ajustes':
            mainContent.innerHTML = 'Sistema reconectando, espera ...';
            break;
        }
      }
      return console.log(j.result);
    }
    j = j.result;
  }
  
  switch (Object.keys(j)[0]) {
  case 'update': onUPD(j); break;

  // 2026-03-04 TODO : WHERE is 'lastentry' from?
  case 'lastentry':
    pv.lastentry = j.lastentry;
    if (pvm.menu == 'Info') showInfo();
    break;

  case 'id':
    if (device.innerHTML == '') { 
      device.innerHTML = j.id;
      document.title = 'CHI Smart ' + j.id;
    }
    // FOR SRV START
    if (!j.wifi) break;
    ws_e.innerHTML = 'Conectado';
    // FOR SRV END
    pve.info = j;

    if (!pvm.menu) break;
    showMain();
    // if ((pvm.menu == 'Sistema') && (pvm.menuSistema == 'Wifi')) showWifi();
    // else if (pvm.menu == 'Info') showInfo();
    break;

  case 'uptime':
    if (typeof pve.info === 'undefined') break;
    let pp = pve.info, p1 = j.wifi.sta;;
    pve.infod = j;
    pp.fecha = j.fecha;
    pp.uptime = j.uptime;
    pp.ram = j.ram;
    pp.fs = j.fs;
    if (j.uart_err_count) pp.uart_err_count = j.uart_err_count;
    if (j.uart) {
      if (pp.ping_count) {
        pp.ping_count = j.ping_count;
        pp.trap_count = j.trap_count;
      }
      pp.uart = j.uart;
    }
    pp = pp.wifi;
    pp.sta.rssi = p1.rssi;
    pp.sta.routertime = p1.routertime;
    pp.sta.sntp = p1.sntp;
    pp.mqtt.d = j.wifi.mqtt.d;
    pp.mqtt.connected = ((pp.mqtt.d > 0) ? 'si' : 'no');
    if (pvm.menu == 'Info') showInfo();
    break;

  case 'wifi':
    pve.scanwifi = 2;
    pve.wifi = j.wifi;
    if (!pvm.menu) break;
    if ((pvm.menu == 'Sistema') && (pvm.menuSistema == 'Wifi')) showWifi();
    break;

  case 'hdmt_nodos':
    pve.hdmt_nodos = j.hdmt_nodos;
    console.log(j);
    break;

  case 'hdmt_nodo':
    console.log(j.hdmt_nodo.data);
    if (typeof pve.hdmt_nodos === 'undefined') break;
    pve.hdmt_nodos.forEach(m => {
      if (m.mac == j.hdmt_nodo.mac){
        if (typeof j.hdmt_nodo.pair !== 'undefined') {
          m.pair = j.hdmt_nodo.pair;
          return;
        }
        if (typeof m.tipo === 'undefined') {
          m.tipo = j.hdmt_nodo.tipo;
          if ((pvm.menu == 'Sistema') && (pvm.menuSistema == 'Entradas')) {
            showEntradas();
          }
        }
        m.data = j.hdmt_nodo.data;
        
      }
    });

  // 2026-03-04 TODO : Where is 't' from?
  case 't':
    if (j.status == 'server disconnected') {
      delete pv.b;
      mainTab.style.display = 'none';
      mainContent.innerHTML = 'servidor no responde';
    } else if (j.status == 'disconnected') {
      console.log(pv.c_msg);
      delete pv.b;
      mainTab.style.display = 'none';
      mainContent.innerHTML = 'fuera de línea';
    }
    break;

  // FOR SRV START
  case 'config_view': // show pic configuration recall command.
    pv.config_view = j.config_view;
    if (ge('config_view')) config_view.innerHTML = update_config_view();
    break;
  // FOR SRV END

  // case 'hdmt': console.log(j); break;
  default: console.log(j); break;
  }
};

// FOR SRV START
ws_open = () => {
  cst.style.backgroundColor = '#FFFDD9';
  ws_e.innerHTML = (pve.info && 'Conectado' || 'fuera de línea');
  pv.c_msg = 0;
  showMain()
};
// FOR SRV END
_nbsp = '<div>&nbsp;</div>';

_b = (a, b, i, d) => '<div><button' + ((typeof d === 'undefined') ? '' : (' style="visibility:' + d + '"')) + ((typeof i === 'undefined') ? '' : (' id=' + i))+ ' onClick=' + a + ' ><svg viewBox="-35 -20 70 32"><text>' + b + '</text></svg></button></div>';

_s2l = t => '<svg viewBox="0 0 80 30"><rect fill=none /><foreignObject x=0 y=0 width=80 height=30><div>' + t + '</div></foreignObject></svg>';

_b2l = (a, b, i) => '<div><button' + ((typeof i === 'undefined') ? '' : (' id=' + i))+ ' onClick=' + a + ' >' + _s2l(b) +'</button></div>';


_div2_svg = (t, p, u) => '<div><svg viewbox="-' + (p * 1.5) + ' -13 ' + (p * 3) + ' 20"><text' + (u ? ' style="text-decoration:underline;" ' : '') + '>' + t + '</text></svg></div>';
_div3_svg = (t, u) => '<div><svg viewbox="-50 -13 100 20"><text' + (u ? ' style="text-decoration:underline;" ' : '') + '>' + t + '</text></svg></div>';
_div3_svg_2l = (t, u) => '<div><svg viewbox="-0 0 110 40"><rect fill=none /><foreignObject x=0 y=0 width=110 height=40><div' + (u ? ' style="text-decoration:underline;" ' : '') + '>' + t + '</div></foreignObject></svg></div>';

_menu_b = (a, b) => '<button onclick=' + a + ' ><svg viewBox="-27 -13 54 16"><text style=font-size:14 >' + b + '</text></svg></button>';

// Salidas y Entradas
_gpio_svg = (t, p, u) => '<div><svg viewbox="-' + (p * 2) + ' -20 ' + (p * 4) + ' 30"><text' + (u ? ' style="text-decoration:underline;font-weight:bold;" ' : '') + '>' + t + '</text></svg></div>';
_b10 = (i, t, c) => '<div><button' + ((i == '') ? '' : (' id=' + i)) + c + ' ><svg viewBox="-10 -15 20 20"><text>' + t + '</text></svg></button></div>';

// Wifi y Info
_rssiToStrength = r => ((r === 0 || r <= -100) ? 0 : ((r >= -50) ? 100 : (2 * (r + 100))));

// Wifi y error
_showModal = (t, m) => {
  hdmtAlertTitle.innerHTML = t;
  hdmtAlertMsg.innerHTML = m;
  hdmtAlert.style.display = 'flex';
};
// 2026-03-03 TODO : captive portal not working after AP pass change and reconfig. Find out how to re init captive portal
// 2026-03-09 NOTE : till a solution for ap pass change and captive portal, reset esp after ap pass change


// ----------------------------------------------------------------------------
// Fecha
rFecha = () => rSistema('Fecha');
sFecha = x => {
  if (typeof x === 'undefined') x = hora_pic.value;
  let d = (new Date(new Date(x) - (new Date()).getTimezoneOffset() * 60000)),
  s = x.slice(2,4) + x.slice(5,7) + x.slice(8,10) + d.getUTCDay() + x.slice(11,13) + x.slice(14,16) + ((x.length == 16) ? ("0" + new Date().getSeconds()).slice(-2) : x.slice(17,19));
  delete pv.f; p("#@FS" + s + s + ";"); rSistema('Fecha');
};
syncFecha = () => sFecha((new Date(Date.now() - (new Date()).getTimezoneOffset()*60000)).toISOString());

// if esp time is 1970, set time to client system time
showFecha = () => {
  // var req = new XMLHttpRequest();
  // req.open('GET', location, false);
  // req.send(null);
  // var headers = req.getAllResponseHeaders().split("\n");
  if (typeof pv.f === 'undefined') {
    adminContent.innerHTML = 'Espera...'
    let t = 5, tI = setInterval(() => {
      if (t--) {
        if (typeof pv.f === 'undefined') return p('#@C;');
        else showFecha()
      }
      clearInterval(tI);
    }, 1000);
    return;
  }
  let f = pv.f.f, z = v => ('00' + v).slice(-2); // zero padding
  f = ((f.getFullYear() < (new Date()).getFullYear()) ? new Date() : f);
  pv1.f_new = pv1.f_now = f.getFullYear().toString() + "-" + z(f.getMonth() + 1) + "-" + z(f.getDate()) + "T" + z(f.getHours()) + ":" + z(f.getMinutes()) + ":" + z(f.getSeconds());

  let s = v => '<div><svg viewbox="-30 -15 60 40"><text>' + v + '</text></svg></div>';
  adminContent.innerHTML = '<h3>Fecha y Hora</h3><br><div class=gpiot >' + s(1) + '<div><input id=hora_pic type=datetime-local value=' + pv1.f_now + ' oninput={pv1.f_new=value;Guardar.style.visibility=((pv1.f_new!=pv1.f_now)?"visible":"hidden")} onkeypress={if(event.keyCode==13)setFecha2PIC(hora_pic.value)}></div>' + _b('sFecha(hora_pic.value)', 'Guardar', 'Guardar', 'Hidden') + '</div><h3>O</h3><br><div class=gpiot >' + s(2) + '<div><svg viewBox="0 0 200 40"><rect fill=none /><foreignObject x=0 y=0 width=200 height=40><div>Sincronizar la hora actual con el dispositivo</div></foreignObject></svg></div>' + _b('syncFecha()', 'Sync') + '</div>';
};
// ----------------------------------------------------------------------------
// Botón
rBotón = () => rSistema('Botón');
sBotón = () => {
  if (pv1.LED.enabled != pv.LED.enabled) setConfig('l' + pv1.LED.enabled);
  if (pv1.Boton.enabled != pv.Boton.enabled) setConfig('be' + pv1.Boton.enabled);
  if (pv1.Boton.enabled) pv1.Boton.f.forEach((v, i) => { if (v != pv.Boton.f[i]) setConfig('b' + id2hex(i) + v) });
  delete pv.Boton; delete pv.LED; setConfig('+'); rSistema('Botón')
};

_ubBotón = () => {
  let showBoton = 0;  
  if ((pv1.Boton.enabled != pv.Boton.enabled) || (pv1.LED.enabled != pv.LED.enabled)) {
    showBoton = 1;
  } else {
    pv1.Boton.f.every((v, i) => {
      if (v != pv.Boton.f[i]) { showBoton = 1; return false; }
      return true;
    });
  }
  Cancel.style.visibility = Guardar.style.visibility = (showBoton ? 'visible' : 'hidden');;
};

uBotón = () => {
  if (typeof pv1.Boton === 'undefined') return showBotón();
  le.innerHTML = _s2l(pv1.LED.enabled ? 'LED Habilitado' : 'LED deshabilitado');
  le.style.backgroundColor = pv1.LED.enabled ? 'lightgreen' : 'red';

  be.innerHTML = _s2l(pv1.Boton.enabled ? 'Botón Habilitado' : 'Botón deshabilitado');
  be.style.backgroundColor = pv1.Boton.enabled ? 'lightgreen' : 'red';
  if (!pv1.Boton.enabled) boton_config.style.display = 'none';
  else {
    boton_config.style.display = '';
    pv1.Boton.f.forEach((v, i) => {
      let e = ge('b' + i);
      if (e) {
        e.value = v;
        if (e.value == '') e.value = '00'
      }
    });
  }
  _ubBotón();
};

showBotón = () => {
  if (typeof pv.LED === 'undefined') {
    adminContent.innerHTML = 'Espera...'
    let t = 5, tI = setInterval(() => {
      if (t--) {
        if (typeof pv.f === 'undefined') return p('#@C;');
        else showBotón()
      }
      clearInterval(tI);
    }, 1000);
    return;
  }

  if (!pv1.LED) {
    pv1.LED = JSON.parse(JSON.stringify(pv.LED));
    pv1.Boton = JSON.parse(JSON.stringify(pv.Boton));
  }

  // building options
  let s = i => '<div><select id=b' + i + ' onchange={pv1.Boton.f[' + i + ']=value;_ubBotón()} >' + opt_h + '</select></div>', o = (v, l) => '<option value=' + v + ' >' + l + '</option>', opt_h = o('00', 'Ninguna');
  pv.S.forEach(s => {
    let t = s.tipo;
    if ((t[0] != '0') && (s.estado != 7)) opt_h += o(t, ((s.l != '') ? s.l : s.name));
  });
  if (typeof pv.H !== 'undefined') pv.H.forEach((h, i) => opt_h += o('3' + id2hex(i + 1), ((h.l != '') ? h.l : 'Riego ' + String.fromCharCode(i + 65))));

  let h = '<div class=div3><div><button id=be onclick={pv1.Boton.enabled^=1;uBotón()}></button></div>' + _nbsp + '<div><button id=le onclick={pv1.LED.enabled^=1;uBotón()}></button></div></div><br><div id=boton_config ><div><h1>Funciones por toque del botón</h1><br></div><div class=div2>' + _div2_svg('Cantidad de toques', 50, 1) + _div2_svg('Función', 50, 1) + '</div><div class=div2>' + _div2_svg('1', 50) + _div2_svg('Parada de bomba', 50) + '</div>';

  // building Botón
  pv1.Boton.f.forEach((_, i) => {
    if ((i > 0) && (i < 6)) h += '<div class=div2 >'+ _div2_svg((i + 1), 50) + s(i) + '</div>';
  });
  
  h += '</div><br><div class=div3 >' + _b('rBotón()', 'Cancelar', 'Cancel', 'hidden') + _nbsp + _b('sBotón()', 'Guardar', 'Guardar',  'hidden') + '</div>';
  adminContent.innerHTML = h;
  uBotón();
};

// ----------------------------------------------------------------------------
// Sevicios
var sFW = "", sStatus = "";
updatefw = fw => {
  let r = confirm("Confirmar actualizar " + fw + "?");
  if (r == false) return;

  p((fw == 'ESP') ? 'o' : 'i.p' );
  sFW = fw;
  mainTab.style.display = 'none';
  mainContent.innerHTML = sStatus = 'Updating ' + fw;
};

rs = "Sistema reiniciando, automático pagina recargar en ";
onUPD = j => {
  if (j.update == "NONE") return;
  // if (j.status == "Update applied, rebooting") rl();
  if (sFW == "") sFW = (j.update == 'OTA') ? 'ESP' : j.update;
  sStatus = sFW + " " + (j.status || j.progress || j.err || "");
  mainTab.style.display = "none";
  mainContent.innerHTML = sStatus;
  // rl_pic(); pve = {}; pvm = {}; initMain = 0;
  if (j.step == 2) mainContent.innerHTML = sStatus + ' escribiendo';
  switch (j.status) {
    case "error":
      console.log(j.msg);
      if (typeof pv.hock === "undefined") {
        mainTab.style.display = "";
        p("e"); p("#@C;");
        showMain();
      }
      break;

    case 'Unexpected end of data': p('e.Q');
    case 'completed':
    case 'Update applied, rebooting':
      sFW = "";
      mainContent.innerHTML = rs + t + "s";
      rl_pic(); pve = {}; pvm = {}; initMain = 0;
      var t = ((sFW == "ESP") ? 15 : 2);
      tI = setInterval(() => {
        if ((typeof pv.b !== "undefined") || (t == 0)) {
          mainTab.style.display = "";
          p("e"); p("#@C;");
          showMain();
          return clearInterval(tI);
        }
        mainContent.innerHTML = rs + (--t) + "s";
      }, 1000);
      break;
    // case 'completed': sFW = ''; return;
  }
};

onFD = () => {
  let r = confirm('confirmar por defecto de fábrica?');
  if (r == false) return;
  rl_pic(); p('#@X;');
  mainTab.innerHTML = '';
  mainContent.innerHTML = 'Sistema reset, espera...';
  pvm = {};
  tI = setInterval(() => {
    if (typeof pv.b === 'undefined') p('#@C;');
    else { clearInterval(tI); showMain() }
  }, 3000);
};

onSistemaReset = () => {
  let r = confirm('Confirmar Reset?');
  if (r == false) return;
  p('i.e');
  mainTab.style.display = 'none';
  var tt = 30; // (ws.url.indexOf('wss') == -1) ? ((pve.info.arch.indexOf('8266') >= 0) ? 12 : 5) : 30;
  t = tt;
  mainContent.innerHTML = rs + t + 's';
  rl_pic(); pve = {}; pvm = {}; initMain = 0;
  tI = setInterval(() => {
    if ((typeof pv.b !== 'undefined') || (t == 0)) {
      mainTab.style.display = '';
      p('e'); p('#@C;');
      console.log(pv.b, t);
      showMain();
      return clearInterval(tI);
    } else if ((tt - t) == 2) p('e.Q');
    mainContent.innerHTML = rs + (--t) + 's';
  }, 1000);
};

showServicios = () => {
  let s = t => '<svg viewBox="-45 -15 90 20" ><text>' + t + '</text></svg>', b = (click, t1, t2) => '<div><button onclick=' + click + ' >' + s(t1) + s(t2) + '</button></div>';
  let h = '<div class=div3>' + _b('onSistemaReset()', "Reset") + _nbsp + b('onFD()', 'IR A VALORES', 'DE FÁBRICA') + '</div><br>Firmware update:<br><div class=div3 >';
  if (ws.url.indexOf('wss') == 0) {
    h += ((pve.info.ota == "si") ? _b('updatefw("ESP")', "ESP") : _nbsp);
  } else h += _b('updatefw("ESP")', "ESP");
  h += _nbsp + _b('updatefw("PIC")', "PIC") + '</div>';

  // FOR SRV START
  if (typeof betaAdmin === 'function') h += betaAdmin();
  // FOR SRV END

  adminContent.innerHTML = h;
};

// ----------------------------------------------------------------------------
// menu Admin
gAdmin = s => { // show modal if changes and not saved
  if ((typeof pvm.menuAdmin === 'undefined') || (!ge('Guardar'))) return 0;
  if ((pvm.menu != 'Sistema') || (pvm.menuSistema != 'Admin') || (pvm.menuAdmin != s)) {  
    if (Guardar.style.visibility == 'visible') {
      hdmtGuardarTitle.innerHTML = s;
      _mN.onclick = () => { hG(); window["r" + s](); menu(pvm.menu) };
      _mS.onclick = () => { hG(); window["s" + s](); menu(pvm.menu) };
      _mV.onclick = () => { hG(); pvm.menu = 'Sistema'; pvm.menuSistema = 'Admin'; pvm.menuAdmin = s };
      hdmtGuardar.style.display = 'flex';
      return 1;
    }
  } else {
    if (Guardar.style.visibility == 'visible') return 1;
  }
  return 0;
};

menuAdmin = val => {
  let o = pvm.menuAdmin;
  pvm.menuAdmin = val;
  if (gAdmin(o)) return;
  Array.from(adminTab.children).forEach(v => { v.className = ((v.firstChild.firstChild.innerHTML == val) ? 'active' : '' )});
  pv1 = {};
  window['show' + val]();
};

showAdmin = () => {
  if (sFW != '') {
    mainTab.style.display = 'none';
    mainContent.innerHTML = sStatus;
    return;
  }

  let t = [];
  if (typeof pv.pic_version !== 'undefined') { t.push('Fecha', 'Botón'); }
  t.push('Servicios');
  let h = '<div class="tab tab' + (t.length < 4 ? 4 : t.length) + '" id=adminTab >';
  t.forEach(v => { h += _menu_b('menuAdmin(\'' + v + '\')', v) });
  h += '</div><div class=tabcontent id=adminContent ></div>';
  sistemaContent.innerHTML = h;

  if (typeof pvm.menuAdmin === 'undefined') pvm.menuAdmin = 'Servicios';
  menuAdmin(pvm.menuAdmin);
};
// DEBUG START
// lower = v => v.toLowerCase().replace(/ /g, '_').normalize('NFD').replace(/\p{Diacritic}/gu, '');
//.replace('é','e').replace('á','a');

// r2i = v => '<label class=switch><input type=checkbox onclick={pv.hdmt.invert[ge("' + v + '").value]=this.checked} id="i' + v + '"><span class="slider round"></span></label>';

// window.scrollTo(0, document.body.scrollHeight)
// DEBUG END

var str_cmd = '';
setConfig = s => {
  // Limit packet size to 200, esp8266 UART tx buffer only work with 255 bytes.
  if ((str_cmd.length + s.length) > 200) { p(str_cmd); str_cmd = '#@' + s + ';';
  } else str_cmd += '#@' + s + ';';
  if (s[0] == '+') { p(str_cmd); str_cmd = ''; }
};

rAjustes = s => {
  pv1 = {};
  // Cancel.style.visibility = AjustesGuardar.style.visibility = 'hidden';
  if (pvm.menu == "Ajustes") {
    if (pvm.menuAjustes == s) window["show" + s]();
    else menuAjustes(pvm.menuAjustes)
  }
};

hG = () => hdmtGuardar.style.display = 'none';
gAjustes = s => { // show modal if changes and not saved
  if (typeof pvm.menuAjustes === 'undefined') return 0;
  if ((pvm.menu != 'Ajustes') || (pvm.menuAjustes != s)) {
    if (AjustesGuardar.style.visibility == 'visible') {
      hdmtGuardarTitle.innerHTML = s;
      _mN.onclick = () => { hG(); window["r" + s](); menu(pvm.menu) }; // descatar
      _mS.onclick = () => { hG(); window["s" + s](); menu(pvm.menu) }; // guardar
      _mV.onclick = () => { hG(); pvm.menu = 'Ajustes'; pvm.menuAjustes = s }; // volve
      hdmtGuardar.style.display = 'flex';
      return 1;
    }
  } else {
    if (ge('AjustesGuardar')) {
      if (AjustesGuardar.style.visibility == 'visible') return 1;
    }
  }
  return 0;
};

menuAjustes = val => {
  if (pvm.menuAjustes != val) {
    let o = pvm.menuAjustes;
    pvm.menuAjustes = val;
    if (gAjustes(o)) return;
  }
  Array.from(ajustesTab.children).forEach(v => v.className = ((v.firstChild.firstChild.innerHTML == val) ? 'active' : ''));
  pv1 = {};
  window['show' + val]();
};

showAjustes = () => {
  let t = [];
  pv.Z && (pv.Z.length > 0) && t.push('Riego', 'Zona');
  pv.T && t.push('Tanque');
  pv.P && t.push('Piscina');
  pv.Ciclon && t.push('Ciclon');
  switch (pvm.menuAjustes) {
    case 'Riego':
    case 'Zona': if (!pv.Z) { delete pvm.menuAjustes; delete pvm.menuRiego;} break;
    case 'Tanque': if (!pv.T) delete pvm.menuAjustes; break;
    case 'Piscina': if (!pv.P) delete pvm.menuAjustes; break;
    case 'Ciclon': if (!pv.Ciclon) delete pvm.menuAjustes; break;
  }
  if (typeof pvm.menuAjustes === 'undefined') pvm.menuAjustes = t[0];

  let h = '<div class="tab tab' + (t.length < 4 ? 4 : t.length) + '" id=ajustesTab >';
  t.forEach(v => h += _menu_b('menuAjustes("' + v + '")', v) );

  mainContent.innerHTML = h + '</div><div class=tabcontent id=ajustesContent ></div><hr><div class=div3 >' + _b('window["r"+pvm.menuAjustes]()', 'Cancelar', 'Cancel', 'hidden') + _nbsp + _b('window["s"+pvm.menuAjustes]()', 'Guardar', 'AjustesGuardar', 'hidden') + '</div>';
  menuAjustes(pvm.menuAjustes);
};
rCiclon = () => rAjustes('Ciclon');
sCiclon = () => {
  let a = pv.Ciclon, b = pv1.Ciclon;
  if (a.modo_ante_tareas != b.modo_ante_tareas) setConfig('C1M' + b.modo_ante_tareas);
  if (a.d_ante_tareas != b.d_ante_tareas) setConfig('C1D' + b.d_ante_tareas);
  if (a.modo_fin_de_tareas != b.modo_fin_de_tareas) setConfig('C2M' + b.modo_fin_de_tareas);
  if (a.d_fin_de_tareas != b.d_fin_de_tareas) setConfig('C2D' + b.d_fin_de_tareas);
  if (a.modo_tiempo != b.modo_tiempo) setConfig('C3M' + b.modo_tiempo);
  if (a.bomba_marcha_duracion != b.bomba_marcha_duracion) setConfig('C3D' + b.bomba_marcha_duracion);
  delete pv.Ciclon; setConfig('+'); rAjustes('Ciclon')
};

_ubCiclon = () => {
  let m = pv.Ciclon, m1 = pv1.Ciclon;
  Cancel.style.visibility = AjustesGuardar.style.visibility = (((m.modo_ante_tareas != m1.modo_ante_tareas) || (m.d_ante_tareas != m1.d_ante_tareas) || (m.modo_fin_de_tareas != m1.modo_fin_de_tareas) || (m.d_fin_de_tareas != m1.d_fin_de_tareas) || (m.modo_tiempo != m1.modo_tiempo) || (m.bomba_marcha_duracion != m1.bomba_marcha_duracion)) ? 'visible' : 'hidden')
};

_uCiclon = (d) => {
  let b,em,ed,h,m;
  switch (d) {
    case 1: m = 'modo_ante_tareas'; h = 'Automático ante tareas'; em = C1M; ed = C1D; break;
    case 2: m = 'modo_fin_de_tareas'; h = 'Automático cuando fin de tareas'; em = C2M; ed = C2D; break;
    case 3: m = 'modo_tiempo'; h = 'Automático con Tiempo de Marcha de Bomba'; em = C3M; ed = C3D; break;
  }
  b = pv1.Ciclon[m];
  em.firstChild.children[1].firstChild.innerHTML = (b ? '' : 'No ') + h;
  em.style.backgroundColor = (b ? 'lightgreen' : 'red');
  ed.disabled = !b;
  _ubCiclon()
};

uCiclon = () => {
  if (!pv1.Ciclon) return showAjustes();
  _uCiclon(1); _uCiclon(2); _uCiclon(3);
  let c = pv1.Ciclon;
  C1D.value = c.d_ante_tareas;
  C2D.value = c.d_fin_de_tareas;
  C3D.value = c.bomba_marcha_duracion;
  _ubCiclon()
};

showCiclon = () => {
  if (typeof pv.Ciclon === 'undefined') return;
  if (!pv1.Ciclon) pv1.Ciclon = JSON.parse(JSON.stringify(pv.Ciclon)); // clone object

  let __s2l = t => '<svg viewBox="0 0 150 30"><rect fill=none /><foreignObject x=0 y=0 width=150 height=30><div>' + t + '</div></foreignObject></svg>', 
  __b2l = (a, b, i) => '<div><button' + ((typeof i === 'undefined') ? '' : (' id=' + i))+ ' onClick=' + a + ' >' + __s2l(b) +'</button></div>',
  _i = (id, max, d, unit) => '<div><input id=' + id + ' type=number min=1 max=' + max + ' oninput={validity.valid||(value="");pv1.Ciclon.' + d + '=value;_ubCiclon()} onkeypress={if(event.keyCode==13)blur()} onblur={value=((value<min)?min:value)} > ' + unit + '</div>';

  let h = '<div class=div2>' + _div2_svg('Modo', 50, 1) + _div2_svg('Duración', 50, 1) + '</div><div class=div2>' + __b2l('{pv1.Ciclon.modo_ante_tareas^=1;_uCiclon(1)}', '', 'C1M') + _i('C1D', 600, 'd_ante_tareas','s') + '</div><div class=div2>' + __b2l('{pv1.Ciclon.modo_fin_de_tareas^=1;_uCiclon(2)}', '', 'C2M') + _i('C2D', 60, 'd_fin_de_tareas', 's') + '</div><div class=div2>' + __b2l('{pv1.Ciclon.modo_tiempo^=1;_uCiclon(3)}', '', 'C3M') + _i('C3D', 9999, 'bomba_marcha_duracion', 'min') + '</div>';

  ajustesContent.innerHTML = h;
  uCiclon();
};
rEntradas = () => rSistema('Entradas');
sEntradas = () => {
  pv1.E.forEach((m, i) => { 
    let m1 = pv.E[i],s = 'E' + i;
    if (m.tipo != m1.tipo) setConfig(s + 'T' + id2hex(m.tipo));
    if (m.invert != m1.invert) setConfig(s + 'I' + m.invert);  // #@EeIv
  });

  if (pv1.B.t3_pozoseco != pv.B.t3_pozoseco) setConfig('BT3' + (t_pozoseco.value));
  if (pv1.B.t4_pozoseco_auto_recover != pv.B.t4_pozoseco_auto_recover) setConfig('BT4' + (t_pozoseco_auto_recover.value * 60));
  pv = { c_msg: 0 }; setConfig('+'); rSistema('Entradas')
};

_ubEntradas = () => {
  let showBoton = 0;
  if ((pv1.B.t3_pozoseco != pv.B.t3_pozoseco) || (pv1.B.t4_pozoseco_auto_recover != pv.B.t4_pozoseco_auto_recover)) showBoton = 1;
  else {
    pv1.E.forEach((m, i) => { 
      let m1 = pv.E[i];
      if ((m.tipo != m1.tipo) || (m.invert != m1.invert)) showBoton = 1;
    });
  }
  Cancel.style.visibility = Guardar.style.visibility = (showBoton ? 'visible' : 'hidden');;
};

var opt_e = '';
uEntradas = () => {
  if (typeof pv1.E === 'undefined') return showEntradas();

  let _eSelect = i => '<select id=E' + i + ' style=margin-top:20px; onchange=onEntradasTipo(' + i + ',this.selectedIndex)>' + opt_e + '</select>';

  pv1.E.forEach((m, i) => {
    // add parameters for detect agua
    let v = m.tipo, e = ge('TDE' + i);
    if ((pv.pic_version >= 360) && (v == 1)) {
      e.innerHTML = _eSelect(i) + '<br>Retraso en la hora de inicio :<input id=t_pozoseco type=number min=0 max=65 oninput={validity.valid||(value="");pv1.B.t3_pozoseco=value;_ubEntradas()} onkeypress={if(event.keyCode==13)blur()} onblur={value=((value<min)?min:value)} value=' + pv1.B.t3_pozoseco + ' > s<br>Reintentar después :<input id=t_pozoseco_auto_recover type=number min=0 max=1440 oninput={validity.valid||(value="");pv1.B.t4_pozoseco_auto_recover=value;_ubEntradas()} onkeypress={if(event.keyCode==13)blur()} onblur={value=((value<min)?min:value)} value=' + (pv1.B.t4_pozoseco_auto_recover / 60) + ' > minutos';
    } else if (e.innerHTML.indexOf('Retraso')) e.innerHTML = _eSelect(i);
    ge('E' + i).value = v;

    let c = 'lightgrey';
    if (pv.E[i].tipo == m.tipo) {      
      switch(pv.E[i].estado) {
      case 0: c = 'transparent'; break;
      case 1: c = 'lightgreen'; break;
      default: c = 'red'; break;
      } 
    }
    ge('E' + i + 'E').style.backgroundColor = c;


    e = ge('E' + i + 'I');
    if (v == 13) e.style.visibility = 'hidden';
    else {
      e.style.visibility = 'visible';
      v = m.invert;
      e.firstChild.firstChild.innerHTML = (v ? 'SI': 'NO');
      e.style.backgroundColor = (v ? 'orange': 'lightgreen');
    }
  });
  _ubEntradas();
};

onEntradasTipo = (k, tipo) => {
  let swap = 0; e = pv1.E[k];
  switch (tipo) {
    case 0: e.invert = 0; break;
    default:
      let inv = e.invert; // swap entradas if exists
      pv1.E.forEach((m, i) => {
        if ((i != k) && (m.tipo == tipo)) {
          m.tipo = e.tipo;
          e.invert = m.invert;
          m.invert = inv;
          swap = 1;
        }
      });

      break;
  }
  if (tipo == 13) e.invert = 0;
  if (swap == 0) {
    if (pv.E[k].tipo == tipo) e.invert = pv.E[k].invert;
  }
  e.tipo = tipo; uEntradas()
};

onNodosTipo = (i, j, s) => {
  let n = pv1.hdmt_nodos[i];

  p('#@EN' + n.mac + 'E' + j + 'T' + n.tipo[j] + 'S' + s);
  p('e.np ' + pve.info.mac);

};

// TO Enable instant entrada respond, call '#@EY;'
showEntradas = () => {
  if (typeof pv.b === 'undefined') {
    tI = setInterval(() => {
    if (typeof pv.b === 'undefined') p('#@C;');
    else { clearInterval(tI); showEntradas() }
    }, 3000);
    return;
  }

  if (typeof pve.hdmt_nodos === 'undefined') {
    p('e.ns');
  }

  // clone object
  if (typeof pv1.E === 'undefined') {
    pv1.E = JSON.parse(JSON.stringify(pv.E));
    pv1.B = JSON.parse(JSON.stringify(pv.B));
  }

  if (opt_e == '') {
     ['Ninguna', 'Detector de agua', 'Sensor de Lluvia', 'Tanque 1 vacío', 'Tanque 1 lleno', 'Tanque 2 vacío', 'Tanque 2 lleno', 'Tanque 3 vacío', 'Tanque 3 lleno', 'Tanque 4 vacío', 'Tanque 4 lleno', 'Pausa-SÍ', 'Pausa-NO', 'Boton'].forEach((t, i) => { 
// FOR SRV START
      if ((t == 'Boton') && (pv.pic_version < 705)) return;
// FOR SRV END
      opt_e += '<option value=' + i + ' >' + t + '</option>'
    });
  }

  let h = '<div class=gpiot >' + _gpio_svg('Entrada', 20, 1) +  _gpio_svg('Módulo', 60, 1) + _gpio_svg('Invertir', 20, 1) + '</div>';
  pv1.E.forEach((_, i) => h += '<div class=gpio>' + _b10('E' + i + 'E', (i + 1), ' style="border:none;outline:none;"') + '<div id=TDE' + i + '></div>' + _b10('E' + i + 'I', '', ' onclick={pv1.E[' + i + '].invert^=1;uEntradas()}') + '</div>' );

  
  if (typeof pve.hdmt_nodos !== 'undefined') {
    if (typeof pv1.hdmt_nodos === 'undefined') pv1.hdmt_nodos = JSON.parse(JSON.stringify(pve.hdmt_nodos));
    let _b10 = (i, t, c) => '<div><button' + ((i == '') ? '' : (' id=' + i)) + c + ' ><svg viewBox="-20 -15 40 20"><text>' + t + '</text></svg></button></div>';
    pv1.hdmt_nodos.forEach((m, i) => {
      if (typeof m.tipo === 'undefined') {
        if (typeof pve.hdmt_nodos[i].tipo === 'undefined') return;
        m.tipo = JSON.parse(JSON.stringify(pve.hdmt_nodos[i].tipo));
      }

      h += '<h3>HDMT/' + m.mac + '</h3>';
      m.tipo.forEach((t, j) => {
        switch (t) {
          case '21':
            let opt = '<option value=0>Ninguna</option>';
            pv.S.forEach(s => {
              if (s.tipo[0] == '2') 
                opt += '<option value=' + s.tipo + ' >' + ((s.l == '') ? ('Tanque ' + s.tipo[1]) : s.l) + '</option>'
            });
            
            let s = 'N' + i + 'E' + j;
            h += '<div class=gpio>' + _b10(s + 'E', 'Nivel ' + (j + 1), ' style="border:none;outline:none;"') + '<div><select id=' + s + 'T style=margin-top:20px; onchange=onNodosTipo(' + i + ',' + j + ',this.selectedIndex)>' + opt + '</select></div></div>'
        }
      });
    });
  }

  h += '<hr><div class=div3 >' + _b('window["r"+pvm.menuSistema]()', 'Cancelar', 'Cancel', 'hidden') + _nbsp + _b('window["s"+pvm.menuSistema]()', 'Guardar', 'Guardar', 'hidden') + '</div>';
  sistemaContent.innerHTML = h;
  uEntradas()
};
// 2026-02-02 TODO : show collapsable structure info
// Example - https://www.w3schools.com/howto/howto_js_collapsible.asp

// 2026-02-09 rename 1_collapsable_content with css extentsion to activate the collapsable content, pending background coloring and stability issue at loading time. Observed when shortening "if" statement to single line helps to reduce delay loading and better respond to click.

coll = e => {
  e.classList.toggle('active');
  let ns = e.nextElementSibling;
  ns.style.maxHeight = ((ns.style.maxHeight.length != 0) ? null : (ns.scrollHeight + 'px'));
};

showInfo = () => {
  if (typeof pve.info === 'undefined') { mainContent.innerHTML = 'Esperando a que el sistema responda...'; return }
  let h0 = t => '<div class=collapsible onclick=coll(this) style=text-align:left;>' + t + '</div><div class=coll-content >';
  let h1 = (t, t2) => '<div class=info ><div>' + t + '</div><div>:</div><div>' + t2 + '</div></div>';
  
  let h = '<br>', m = pve.info.wifi, n = m.sta;
  if (n.ssid != '') { 
    h += h0('WIFI') + h1('Red Wifi', n.ssid);
    if (n.connected == 'conectado') {
      h += h1('SNTP', n.sntp.toUpperCase()) + h1('DHCP', n.dhcp) + h1('GW', n.gw) + h1('IP', n.ip) + h1('Nivel de señal', _rssiToStrength(n.rssi) + '%') + h1('Tiempo conectado', n.routertime + ' s');
      if (m.mqtt) {
        n = m.mqtt;
        h += '</div>' + h0('MQTT');
        if (typeof n.enable !== 'undefined') h += h1('Conectado', n.connected.toUpperCase());
        if (typeof n.d !== 'undefined') h += h1('Tiempo conectado', n.d + ' s');
      }
    } else {
      h += h1('Estado', n.connected.toUpperCase());
      h += h1('código', n.reason) + h1('reintentos', n.retry);
      switch (n.reason) {
        case 201: h += h1('Mensaje', 'SSID no existe'); break;
        case 202: h += h1('Mensaje', 'Contraseña incorrecta'); break;
      }
    }
    h += '</div><br>';
  }

  h += h0('Sistema');

  if (typeof pv.pic_version !== 'undefined') {
    m = pv.Batería;
    h += h1('Tipo', pv.pic_name) +  h1('Version PIC', pv.pic_version) + h1('Chip ID', pv.pic_id + ', ' + pv.pic_rev) + h1('PIC Fecha', pv.f.f.toLocaleString('es-AR', {dateStyle:'short', timeStyle:'short'}));
    if (typeof pv.B !== 'undefined') h += h1('Bomba Marcha', pv.B.marcha + ' minutos');
    h += h1('Batería', ((m == 0) ? 'sin Batería' : m + '%'));
    if (typeof pic_info !== 'undefined') h += pic_info();
    h += '<br>';
  }

  m = pve.info;
  if (m.pic_id) h += h1('Chip ID', m.pic_id) + '<br>';
  if (m) {
    h += h1('ID del dispositivo', m.id) + h1('Vesion ESP', m.fw_version) + h1('OTA', m.ota.toUpperCase()) + h1('OS', m.mg_version) + h1('Mac addr', m.mac) + h1('Slot activo', m.active_slot) + h1('Memoria libre', m.ram.free) + h1('Memoria libre min ', m.ram.min_free) + h1('Tiempo Energizado', m.uptime + ' s') + h1('Contador de mensajes', pv.c_msg);

    // m = m.wifi;
    // let n = m.activ;
    // h += h0('Conexiones') + h1('contar', n.length);
    // for (i in n) h += h1('conn ' + i, n[i].ip);
    n = m.wifi.ap;
    h += h1('AP SSID', n.ssid) + h1('AP IP', n.ip == '' ? 'deshabilitar' : n.ip); // + h1('MAC', n.mac);

    // FOR SRV START - admin only
    if (typeof err_info !== 'undefined') h += err_info(m);
    // FOR SRV END
  }
  
  h += '</div>';
  if (pv.lastentry) h += '<br>' + h1('Última conexión', pv.lastentry);

  h += '<br><hr><div><label><svg viewBox="-250 -13 500 18"><text><tspan>Ultimo Evento: <tspan id="' + ur + '">' + pv[ur] + ' </tspan></tspan></label></div>';
  
  // if (typeof betaInfo === 'function') h += betaInfo();
  mainContent.innerHTML = h;
  // if (typeof getLocation === 'function') getLocation();
};
var initMain = 0;
var IpvbC, Ipvb;
menu = val => {
  if (!ws && (reconnect_count == 0)) { reconnect_count = 3; reconnect_ws(); }
  let o = pvm.menu;
  pvm.menu = val;
  switch (o) {
    case 'Ajustes':
      if (gAjustes(pvm.menuAjustes)) return;
      break;

    case 'Sistema':
      if (gSistema(pvm.menuSistema)) return;
      break;
  }
  
  Array.from(mainTab.children).forEach(v => { v.className = ((v.firstChild.firstChild.innerHTML == val) ? 'active' : '' )});
  mainContent.style.display = '';
  pv1 = {};
  switch (val) {
  case 'Sistema':
    if (pvm.menuSistema == 'Wifi') pve.mWifi--;
    showSistema();
    break;

  case 'Info':
    if (ws) {
      if (typeof pve.info === 'undefined') {
        setTimeout(() => {if (typeof pve.info === 'undefined') p('e')}, 500);
      } else p('e.d');

      // p((typeof pve.info === 'undefined') ? 'e' : 'e.d'); // e - full packet, e.d - dynamic data packet
      if (typeof pv.b !== 'undefined') {
        if (ws.url.indexOf('wss') == 0) setTimeout(() => p('#@C;'), 500);
        else p('#@C;');
      } else {
        if (Ipvb == null) {
          IpvbC = 3;
          // p('#@C;');
          Ipvb = setInterval(() => {
            if (pv.b) { clearInterval(Ipvb); Ipvb = null; return; }
            IpvbC--;
            if (IpvbC) p('#@C;');
            else { clearInterval(Ipvb); Ipvb = null; }
          }, 3000);
        }
      }
    }
  default:
    window['show' + val]();
  }
};

showMain = () => {
  let t = [];
  if (typeof pv.pic_version !== 'undefined') {
    t.push('Manual');
    if (pv.Z || pv.T || pv.P) t.push('Ajustes');
  }
  // FOR SRV START
  if (typeof pve.info !== 'undefined')
  // FOR SRV END  
    t.push('Sistema');
  t.push('Info');
  if ((initMain == 0) && (t.length == 4)) {
    initMain = 1;    
    if (pve.info) {
      switch (pve.info.wifi.sta.reason) {
        case 201:
        case 202: break;
        default: pvm.menu = t[0]; // 'Manual';
      }
    }
  }

  let l = mainTab.children.length;
  if (l != t.length) {
    let h = '', tl = 'tab' + t.length;
    t.forEach(v => h += _menu_b('menu(\'' + v + '\')', v));
    mainTab.style.display = '';
    // if (l == 0) mainTab.classList.add(tl);
    // else mainTab.classList.replace('tab' + mainTab.children.length, tl);
    mainTab.innerHTML = h;
    if (typeof pvm.menu === 'undefined') pvm.menu = (pv.b ? 'Manual' : 'Info');
    menu(pvm.menu);
  }
};uManual = () => showManual();

getIcon = e => {
  switch (e) {
  // case 4: return 'pause';
  case 0:
  case 5: return 'play';
  }
  return 'stop';
};

getEstadoClick = e => {
  switch (e) {
  // case 4: return (pv.B.entrada.estado == 1) ? '';
  case 0:
  case 5: return '1';
  }
  return '0';
};

getEstadoColor = e => {
  let s;
  switch (e) {
    case -1 : s = 'gray'; break;
    case 0: return '';
    case 1: s = 'lightgreen'; break;
    case 2: s = 'red'; break;
    case 3: s = 'orange'; break;
    case 4: s = 'yellow'; break;
    case 5: s = 'magenta'; break;
    default: s = e;
  }
  return 'style=background-color:' + s + ' ';
};

getEntradaColor = e => {
  let s;
  switch (e) {
    case 0: return '';
    case 1: s = 'lightblue';
    case 2:
    case 3: s = 'red';
    default: s = e;
  }
  return 'style=background-color:' + s + ' ';
};

let ti_bomba, toggle_bomba_color = 0;
showManual = () => {
  "use strict";
  let es, l, ri, t, h = '<svg style=display:none x=0px xmlns=http://www.w3.org/2000/svg xmlns:xlink=http://www.w3.org/1999/xlink><symbol id=play viewBox="00 00 512 512"><path d="M371.7 238l-176-107c-15.8-8.8-3.7 2.5-35.7 21v208c0 18.4 19.8 29.8 35.7 21l176-101c16.4-9.1 16.4-32.8 0-42zM504 256C504 119 393 8 256 8S8 119 8 256s111 248 248 248 248-111 248-248zm-448 0c0-110.5 89.5-200 200-200s200 89.5 200 200-89.5 200-200 200S56 366.5 56 256z"/></symbol><symbol id=stop viewBox="0 0 24 24"enable-background="new 0 0 24 24"xml:space=preserve><g transform="translate(-5.000000,-7.000000) scale(1.45000000,1.4500000)"><path d="M12,6c3.9,0,7,3.1,7,7s-3.1,7-7,7s-7-3.1-7-7S8.1,6,12,6 M12,5c-4.4,0-8,3.6-8,8s3.6,8,8,8s8-3.6,8-8S16.4,5,12,5L12,5z"/><rect height=6 width=6 x=9 y=10 /></g></symbol><symbol id=pause viewBox="0 0 512 512"><path d="M464 256A208 208 0 1 0 48 256a208 208 0 1 0 416 0zM0 256a256 256 0 1 1 512 0A256 256 0 1 1 0 256zm224-72l0 144c0 13.3-10.7 24-24 24s-24-10.7-24-24l0-144c0-13.3 10.7-24 24-24s24 10.7 24 24zm112 0l0 144c0 13.3-10.7 24-24 24s-24-10.7-24-24l0-144c0-13.3 10.7-24 24-24s24 10.7 24 24z"/></symbol></svg>';
 
  // reuse function
  // a - svg text, s - salida button, e - entrada button

  // es - estado, c - cmd, t - title, e ? - estado para icon
  let s = (es, c, t, e, id) => '<div><button ' + (id ? 'id=' + id +' ' : '') + getEstadoColor(es) + 'onclick="' + c + '" >' + _s2l(t) + '<br><svg width=40 height=40 ><use xlink:href=#' + getIcon(e) + ' /></svg></button></div>',
    e = (es, t1) => '<div><button ' + getEntradaColor(es) + '>' + _s2l(t1) + '</button></div>';

  if (typeof pv.S === 'undefined') {
    p('#@C;'); mainContent.innerHTML = '<h3>Espera...</h3>'; return;
  }
  
  let hay_salida_config = 0, hay_salida_conectando = 0;
  for (l = 0; l < pv.S.length; l++) {
    switch (pv.S[l].tipo) {
      case '00':
      case '61':
        break;
      default:
        hay_salida_config = 1;
        if (pv.S[l].estado != 7) hay_salida_conectando++;
    }
  }

  if (hay_salida_config == 0) {
    h += '<hr><div><label><svg viewBox="-250 -13 500 18"><text><tspan>Ultimo Evento: <tspan id="' + ur + '">' + pv[ur] + ' </tspan></tspan></label></div><br><a href=# >Top</a>';
    mainContent.innerHTML = '<h1>No hay ninguna salida configurada!</h1>';
    return;
  } else if (hay_salida_conectando == 0) {
    h += '<hr><div><label><svg viewBox="-250 -13 500 18"><text><tspan>Ultimo Evento: <tspan id="' + ur + '">' + pv[ur] + ' </tspan></tspan></label></div><br><a href=# >Top</a>';
    mainContent.innerHTML = '<h1>No hay ninguna salida conectada!</h1>';
    return;
  }

  if (typeof pv.B === 'undefined') return;
  if (pv.B.estado != 11) {
    if (ti_bomba) clearInterval(ti_bomba);
    ti_bomba = null;
  }
  h += '<div class=div3>' + s(pv.B.estado, 'p(\'#@B0;\')', 'Bomba', 1, 'bomba');
  if (pv.B.estado == 11) { h += '<div>Bomba en recuperación</div>';
  } else if (pv.B.estado == 5) { h += '<div>No se detecta agua</div>';
  } else {
    switch (pv.B.pausa_externa) {
      case 1: h += e('lightblue', 'Pausa externa'); break;
      case 2: h += e(2, 'Pausa externa falla'); break;
      default: h += _nbsp;
    }
    if (pv.Ciclon && (pv.Ciclon.s.estado == 1)) h += s(1, 'p(\'#@S' + id2hex(pv.Ciclon.s.id) + 'M0;\')', (pv.Ciclon.s.l ? pv.Ciclon.s.l : pv.Ciclon.s.name), 1);
  }
  h += '</div>';

  // shared code between Manguera, Zona y Piscina
  let _layout = mo => {
    h += '<br>';
    l = ri = 0;
    mo.forEach(() => l++);
    mo.forEach(m => {
      if (ri == 0) h += '<div class=div3>';
      es = m.s.estado;
      let es1 = ((m.s.tipo[0] == '1') ? ((pv.B.pausa_externa != 0) ? -1 : es) : es);
      h += s(es1, 'p(\'#@S' + id2hex(m.s.id) + 'M' + (es == 0 ? 1 : 0) + ';\')', (m.s.l != '' ? m.s.l : m.s.name), es);
      ri++; if (ri == 3) { h += '</div>'; ri = 0 }
    });
    if (ri != 0) h += '</div>';
  };

  // Show manguera boton in gris when pausa externa is activated!
  if (pv.M) _layout(pv.M); // manguera id, estado, salida id

  if (pv.T) { // Tanque id, estado, nivel, salida id, flotante id, aux id, modo, duración
    h += '<br>';
    l = 0;
    pv.T.forEach(() => l++);
    pv.T.forEach(m => {
      es = 0;
      switch(m.s.estado) {
      case 0: // desactivado
      // case 4: // pausa
      case 5: es = 1; // timeout
      }
      h += '<div class=div3>' + s(m.s.estado, 'p(\'#@S' + id2hex(m.s.id) + 'M' + es + ';\')', ((l > 1) ? (m.s.l != '' ? m.s.l :m.s.name) : 'Tanque'), m.s.estado);
      if (m.nivel != 0xFF) {
        let es = ['Lleno', 'Vacio', 'Sensor Falla', 'Nivel Falla', 'Medio'],
        c = ['#5881FF', '#D6EAF8', 'red', 'red', 'lightblue'];
        h += e(c[m.nivel], es[m.nivel], '');
      }
      h += '</div>';
    });
  }

  if (pv.Z) { // Zona id, estado, salida id, duración
    if (pv.H) { // Riego id, estado, nivel, salida id, flotante id, aux id, modo, duración
      // Horarios, id, estado, Active Zona, Active Zona Remain duración (2), habilitado, hora, minutos, paridad, dias_semana, entrada, zonas duración (12 x 2)
      l = ri = 0; t = '';
      pv.H.forEach((m, i) => {
        let d = 0;
        m.zonas.forEach((v, i) => { if (pv.Z[i]) d += v; });
        if (d == 0) return;
        if (m.habilitado) l++; 
        if (ri == 0) t += '<div class=div3>';
        t += s(m.estado, 'p(\'#@H' + id2hex(i) + 'M' + (m.estado == 0 ? 1 : 0) + ';\')', ((m.l != '') ? m.l : 'Riego ' + String.fromCharCode(m.id + 65)), m.estado);
        ri++;
        if (ri == 3) { t += '</div>'; ri = 0 }
      });
      if (ri != 0) t += '</div>';

      if (l != 0) {
        h += '<br><div class=div3>';
        let a = t => '<svg viewBox="2 -8 74 45"><rect fill=none /><foreignObject x=0 y=0 width=80 height=40><div>' + t + '</div></foreignObject></svg>',
          s = (es, t) => '<div><button ' + es + ' >' + a("Auto Riego " + t) + '</button></div>';

        if (pv.R.modo != 0) {
          h += s('style=background-color:#5881FF onclick=p("#@RA0;#@+;")', 'Activado');
          if (pv.R.sensorDeLluvia == 1) h += s('style=background-color:red;', 'Bloqueado');
        } else h += s('onclick=p("#@RA1;#@+;")', 'Desactivado');
        
        h += '</div>' + t;
      } else if (t.length != 0) h += '<br>' + t;
    }
    _layout(pv.Z);
  }

  if (pv.P) _layout(pv.P); // Piscina id, estado, salida id, duración

  if (pv.L && pv.L.length != 0) {
    let s = (t, p, u) => '<div><svg viewbox="-' + (p * 3) + ' -13 ' + (p * 6) + ' 20"><text' + (u ? ' style="text-decoration:underline;" ' : '') + '>' + t + '</text></svg></div>';
    h += '<hr><div class=tareas>' + s('Nr.', 10, 1) + s('Tarea', 55, 1) + s('Final', 15, 1) + s('Modo', 20, 1) + '</div>';
    pv.L.forEach((m, i) => {
      let tipo_name, duración = "-";
      if ((m.tipo[0]) != '3') {
        pv.S.forEach(s => {
          if (s.tipo == m.tipo) {
            tipo_name = s.l ? s.l : s.name;
            if (i == 0) {
              if ((s.estado != 4) && (s.duración != 0)) {
                l = Date.now() + m.duración * ((s.tipo[0] == '6') ? 1000 : 60000);
                duración = ((m.duración > 1440) ?  ffo({ weekday: 'long', year: 'numeric', month: 'short', day: 'numeric' }, l) + '<br>' : '') + ffo({ hour: 'numeric', minute: 'numeric', hour12: false }, l);
              }
            }
          }
        });
      } else {
        let id = m.tipo.charCodeAt(1);
        id += ((id < 59) ? 16 : 9); 
        tipo_name = 'Riego ' + String.fromCharCode(id); // '1' -> 'A'
        if (i == 0) {
          if (pv.H[hex2int(m.tipo[1]) - 1].estado != 4) {
            l = Date.now() + m.duración * 60000;
            duración = ((m.duración > 1440) ?  ffo({ weekday: 'long', year: 'numeric', month: 'short', day: 'numeric' }, l) + '<br>' : '') +ffo({ hour: 'numeric', minute: 'numeric', hour12: false }, l);
          }
        }
      }
      h += '<div class=tareas>' + s((m.id + 1), 10, 0) + s(tipo_name, 55, 0) + s(duración, 15, 0) + s((m.modo ? 'Auto' : 'Manual'), 20, 0) + '</div>' 
    });
  }

  h += '<hr><div><label><svg viewBox="-250 -13 500 18"><text><tspan>Ultimo Evento: <tspan id="' + ur + '">' + pv[ur] + ' </tspan></tspan></label></div><br><a href=# >Top</a>';
  mainContent.innerHTML = h;

  if ((pv.B.estado == 11) && (ti_bomba == null)) {
    ti_bomba = setInterval(() => {
      if (mainTab.children[0].classList.contains('active') == false) {
        clearInterval(ti_bomba);
        ti_bomba = null;
        return;
      }
      if (toggle_bomba_color) {
        toggle_bomba_color = 0;
        bomba.style.backgroundColor = 'yellow';
      } else {
        toggle_bomba_color = 1;
        bomba.style.backgroundColor = 'lightgreen';
      }
    }, 500);
  }
};
rPiscina = () => rAjustes('Piscina');
sPiscina = () => {
  pv1.P.forEach((m, i) => { if (m) { if ((typeof pv.P[i] === 'undefined') ||  (m.s.duración != pv.P[i].s.duración)) setConfig('S' + id2hex(m.s.id) + 'D' + m.s.duración) }});
  delete pv.P; setConfig('+'); rAjustes('Piscina')
};

_ubPiscina = () => {
  let showBoton = 0;
  pv1.P.forEach((m, i) => { if (m) { if ((typeof pv.P[i] === 'undefined') || (m.s.duración != pv.P[i].s.duración)) showBoton = 1 }});
  Cancel.style.visibility = AjustesGuardar.style.visibility = (showBoton ? 'visible' : 'hidden');
};

uPiscina = () => {
  if (!pv1.P) return showAjustes();
  pv1.P.forEach(m => { if (m) ge('P' + m.id + 'D').value = m.s.duración });
  _ubPiscina()
};

showPiscina = () => {
  if (typeof pv.P === 'undefined') return;
  if (!pv1.P) pv1.P = JSON.parse(JSON.stringify(pv.P)); // clone object

  let h = '<div class=div2>' + _div2_svg('Piscina', 50, 1) + _div2_svg('Duración', 50, 1) + '</div>';
  pv1.P.forEach(m => { if (m) h += '<div class=div2>' + _div2_svg(((m.s.l == '') ? m.id + 1 : m.s.l), 50) + '<div><input id=P' + id2hex(m.id) + 'D type=number min=1 max=9999 oninput={validity.valid||(value="");pv1.P[' + m.id + '].s.duración=value;_ubPiscina()} onkeypress={if(event.keyCode==13)blur()} onblur={value=((value<min)?min:value)} >minuto(s)</div></div>'});

  ajustesContent.innerHTML = h;
  uPiscina()
};
rRiego = () => rAjustes('Riego');
sRiego = () => {
  if (pv1.R.modo != pv.R.modo) setConfig('RA' + pv1.R.modo);;
  pv1.H.forEach((m, i) => {
    let m1 = pv.H[i], s = 'H' + id2hex(i);
    if (typeof m1 === 'undefined') {
      if (m.habilitado != 0) setConfig(s + 'A' + m.habilitado);
      if ((m.horas != 0) || (m.minutos != 0)) setConfig(s + 'H' + ('00' + m.horas).slice(-2) + ('00' + m.minutos).slice(-2));
      if (m.paridad != 0) setConfig(s + 'P' + m.paridad);
      if (m.dias_semana != 127) setConfig(s + 'D' + m.dias_semana);
      if (m.accesorios != 1) setConfig(s + 'X' + m.accesorios);
      else m.zonas.forEach((z, j) => {if (z != 0) setConfig(s + 'Z' + id2hex(j) + 'D' + z)});
    } else {      
      if (m.habilitado != m1.habilitado) setConfig(s + 'A' + m.habilitado);
      if ((m.horas != m1.horas) || (m.minutos != m1.minutos)) setConfig(s + 'H' + ('00' + m.horas).slice(-2) + ('00' + m.minutos).slice(-2));
      if (m.paridad != m1.paridad) setConfig(s + 'P' + m.paridad);
      if (m.dias_semana != m1.dias_semana) setConfig(s + 'D' + m.dias_semana);
      if (m.accesorios != m1.accesorios) setConfig(s + 'X' + m.accesorios);
      m.zonas.forEach((z, j) => {if (z != m1.zonas[j]) setConfig(s + 'Z' + id2hex(j) + 'D' + z)});
    }
  });
  delete pv.R; delete pv.H; setConfig('+'); rAjustes('Riego')
};

_ubRiego = () => {
  let showBoton = 0;
  if (pv1.R.modo != pv.R.modo) showBoton = 1;
  else {
    pv1.H.forEach((m, i) => {
      let m1 = pv.H[i];
      if (typeof m1 === 'undefined') {
        if ((m.habilitado != 0) || (m.horas != 0) || (m.minutos != 0) || (m.paridad != 0) || (m.dias_semana != 127) || (m.accesorios != 1)) showBoton = 1;
        else m.zonas.forEach(z => {if (z != 0) showBoton = 1});
      } else {
        if ((m.habilitado != m1.habilitado) || (m.horas != m1.horas) || (m.minutos != m1.minutos) || (m.paridad != m1.paridad) || (m.dias_semana != m1.dias_semana) || (m.accesorios != m1.accesorios)) showBoton = 1;
        else m.zonas.forEach((z, j) => {if (z != m1.zonas[j]) showBoton = 1});
      }
    });
  }
  Cancel.style.visibility = AjustesGuardar.style.visibility = (showBoton ? 'visible' : 'hidden');;
};

// update Riego Auto y Horario habilitado
_uHabilitado = (b, e1, e2) => {
  e1.innerHTML = (b ? 'H' : 'Desh') + 'abilitado';
  e2.style.backgroundColor = (b ? 'lightgreen' : 'red');
  _ubRiego();
};

updateHorario = v => {
  let m = pv1.H[pvm.menuRiego - 1];
  if (v.length == 5) { v = v.split(':'); m.horas = v[0]; m.minutos = v[1];
  } else horario.value = ('00' + m.horas).slice(-2) +  ':' + ('00' + m.minutos).slice(-2);
  _ubRiego();
};

uDias = v => ge('dia' + v).style.backgroundColor=(((pv1.H[pvm.menuRiego - 1].dias_semana & (1 << v)) != 0) ? 'lightgreen' : 'red');

toggleDias = v => {
  pv1.H[pvm.menuRiego - 1].dias_semana ^= (1 << v);
  uDias(v);
  _ubRiego();
};

uAccesorios = () => {
  let b = pv1.H[pvm.menuRiego - 1].accesorios
  re.innerHTML = _s2l((b ? 'Usar Sensor de Lluvia' : 'No Usar Sensor'));
  re.style.backgroundColor = (b ? 'lightgreen' : '');
  _ubRiego();
};

uRiego = () => {
  if (!pv1.H) return showAjustes();
  _uHabilitado(pv1.R.modo, rAt, rA); // Riego Auto
  _uHabilitado(pv1.H[pvm.menuRiego - 1].habilitado, hhat, hha); // Horario habilitado
  let m = pv1.H[pvm.menuRiego - 1];
  horario.value = ('0' + m.horas).slice(-2) + ':' + ('0' + m.minutos).slice(-2);
  let i = 0;
  for (; i < 7; i++) uDias(i);
  ge('paridad' + m.paridad).checked = true;
  m.zonas.forEach((v, i) => {
    let e = ge('Z' + id2hex(i) + 'D');
    if (e) e.value = v;
  });
  if (ge('re')) uAccesorios();
  _ubRiego()
};

menuRiego = val => {
  pvm.menuRiego = val;
  Array.from(riegoTab.children).forEach(v => { v.className = (v.firstChild.firstChild.innerHTML == String.fromCharCode(val + 64)) ? 'active' : '' });
  uRiego()
};

showRiego = () => {
  if (typeof pv.R === 'undefined') return;
  // clone object
  if (!pv1.H) {
    pv1.R = JSON.parse(JSON.stringify(pv.R)); 
    pv1.H = ((typeof pv.H !== 'undefined') ? JSON.parse(JSON.stringify(pv.H)) : []); 
  }

  let i = 0;  
  for (; i < 12; i++) { // init empty horarios to default value
    if ((typeof pv1.H[i] === "undefined") || (pv1.H[i] == null)) {
      pv1.H[i] = { estado : 0, habilitado : 0, horas : 0, minutos : 0, paridad : 0, dias_semana : 127, accesorios : 1 };
      pv1.H[i].zonas = pv.IsMini ? [0, 0, 0, 0, 0, 0] : [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
    }
  }

  let h = '<br><div class=div3><div><svg viewBox="-60 -25 120 30"><text>AUTO RIEGO :</text></svg></div><div><button id=rA onclick=_uHabilitado(pv1.R.modo^=1,rAt,rA) ><svg viewBox="-40 -12 80 16"><text id=rAt style=font-size:12 ></text></svg></button></div></div><br><div class="tab tab6" id=riegoTab >';

  for (i = 1; i <= 12; i++) h += '<button onclick=menuRiego(' + i + ')><svg viewBox="-15 -17 30 20"><text style=font-size:18>' + String.fromCharCode(i + 64) + '</text></svg></button>';

  h += '</div><div class=tabcontent id=riegoContent ><div class=div3><div><svg viewBox="-40 -16 80 18"><text>Inicio</text></svg></div><div><button id=hha onclick=_uHabilitado(pv1.H[pvm.menuRiego-1].habilitado^=1,hhat,hha) ><svg viewBox="-40 -12 80 16"><text id=hhat style=font-size:12 ></text></svg></button></div><div><input id=horario type=time onkeypress={if(event.keyCode==13)blur()} onchange=updateHorario(value) ></div></div><br>';

  h += 'Días de la semana<div class=div7>';
  let dia = ['D','L','M','M','J','V','S'];
  dia.forEach((m, i) => { h += '<div><button id=dia' + i + ' onclick=toggleDias(' + i + ') ><svg viewBox="-15 -17 30 20"><text style=font-size:18 >' + m + '</text></svg></button></div>'; });

  h += '</div><br><div class=div3>';

  let paridad = ['Todos', 'Impares', 'Pares'], s = t => '<svg viewBox="-40 -14 80 16"><text>' + t + '</text></svg>';
  paridad.forEach((m, i) => { // #@HiPx
    h += '<div><input id=paridad' + i + ' name=paridad type=radio class=with-gap onclick={pv1.H[pvm.menuRiego-1].paridad=' + i + ';_ubRiego()} /><span>' + s(m) + '</span></div>';
  });

  h += '</div><br><div class=div2>' + _div2_svg('Zona', 50, 1) + _div2_svg('Duración', 50, 1) + '</div>';

  pv.Z.forEach(m => { if (m) h += '<div class=div2>' + _div2_svg(((m.s.l == '') ? m.id + 1 : m.s.l), 50) + '<div><input id=Z' + id2hex(m.id) + 'D type=number min=0 max=9999 oninput={validity.valid||(value="");pv1.H[pvm.menuRiego-1].zonas[' + m.id + ']=value;_ubRiego()} onkeypress={if(event.keyCode==13)blur()} onblur={value=((value<min)?min:value)} >minuto(s)</div></div>'});
  
  if (pv.R.sensorDeLluvia != 255) 
    h += '<br><div class=div3>' + _nbsp + '<div><button id=re onclick={pv1.H[pvm.menuRiego-1].accesorios^=1;uAccesorios()} >' + _s2l("Sensor de Lluvia") + '</button></div></div>';
    
  ajustesContent.innerHTML = h;
  if (!pvm.menuRiego) pvm.menuRiego = 1;
  menuRiego(pvm.menuRiego);
};
rSalidas = () => { delete pv.testBoton; rSistema('Salidas') };
sSalidas = () => {
  pv1.S.forEach((m, i) => {
    let c = pv.S[i], s = 'S' + id2hex(i);
    if (m.tipo != c.tipo) setConfig(s + 'T' + m.tipo);    // #@SiTmm - tipo
    if (m.bomba != c.bomba) setConfig(s + 'B' + m.bomba); // #@SiBb - bomba
    if (m.l != c.l) setConfig(s + 'L' + m.l);             // #@SiL... - Label
  });
  pv = { c_msg: 0 }; setConfig('+;#@Q1000'); rSalidas(); 
};

_ubSalidas = () => {
  let showBoton = false;
  pv1.S.forEach((m, i) => {
    let m1 = pv.S[i];
    if ((m.tipo != m1.tipo) || (m.bomba != m1.bomba) || (m.l != m1.l)) showBoton = true
  });
  Cancel.firstChild.firstChild.innerHTML = (showBoton ? 'Cancelar' : 'Clear Test');
  Cancel.style.visibility = ((pv.testBoton || showBoton) ? 'visible' : 'hidden');
  Guardar.style.visibility = (showBoton ? 'visible' : 'hidden');
};

clear_test = () => { delete pv.M; delete pv.T; delete pv.P; delete pv.Z; delete pv.S; delete pv.testBoton; pv1 = {}; p('#@SD;') };

probar = () => { p('#@ST;'); pv.testBoton = 1; pv1 = {}; sistemaContent.innerHTML = 'Probando la salidas ...' };

uSalidas = () => {
  if (typeof pv1.S === 'undefined') return showSalidas();// clone object
  let ss = (typeof pv.testBoton !== 'undefined') ? pv.S : pv1.S; // if test boton press, show data from origin pv, and not pv1.
  
  ss.forEach((m, i) => {
    let c = 'transparent', j = 'S' + i, s = pv.S[i].estado;
    switch (s) {
      case 1: c = 'lightgreen'; break;
      case 2: c = 'red'; break;
      case 7:
      case 3: c = 'orange'; break;
      // default: c = 'transparent'; break;
    }
    ge(j + 'E').style.backgroundColor = c;
    let tipo = ge(j + 'T');
    tipo.value = m.tipo;
    ge(j + 'L').placeholder = ((s == 7) ? 'Deshabilitado' : '- ' + tipo.options[tipo.selectedIndex].text);
    ge(j + 'L').value = (m.l != '' ? m.l : '');

    let b = m.bomba, e = ge(j + 'B');
    e.firstChild.firstChild.innerHTML = (b ? 'SI': 'NO');
    e.style.backgroundColor = (b ? 'lightgreen': 'orange');    
  });
  _ubSalidas()
};

onSalidasTipo = (k, tipo) => {
  let s = pv1.S[k];
  if (tipo != '00') {
    // swap salida if exist
    let b = s.bomba, l = s.l, swap = 0;
    pv1.S.forEach((m, i) => {
      if ((i == k) || (m.tipo != tipo)) return;
      m.tipo = s.tipo;
      s.bomba = m.bomba; m.bomba = b;
      s.l = m.l; m.l = l;
      swap = 1;
    });
    if (swap = 0) {
      if (s.tipo[0] != tipo[0]) s.l = '';
    }
  } else s.l = '';
  s.tipo = tipo;
  uSalidas()
};

var opt_s, tS;
showSalidas = () => {
  if (typeof pv.S === 'undefined') {
    if (tS == null) {
      tS = setInterval(() => {
        if (typeof pv.S === 'undefined') { p('#@C;')
        } else { clearInterval(tS); tS = null; showSalidas() }
      }, 3000);
    }
    return;
  }

  if (typeof pv1.S === 'undefined') pv1.S = JSON.parse(JSON.stringify(pv.S)); // clone object

  if (typeof opt_s === 'undefined') {
    let tl = ['Ninguna', 'Manguera', 'Tanque', '', 'Zona', 'Piscina', 'Ciclon'];
    (pv.IsMini ? ['00', '11', '12', '13', '14', '15', '16', '21', '22', '23', '24', '41', '42', '43', '44', '45', '46', '51', '52', '61'] : ['00', '11', '12', '13', '14', '15', '16', '17', '18', '19', '1A', '1B', '1C', '21', '22', '23', '24', '41', '42', '43', '44', '45', '46', '47', '48', '49', '4A', '4B', '4C', '51', '52', '61']).forEach(t => opt_s += '<option value=' + t + '>' + tl[t[0]] + ((t[1] != '0') ? (' ' + hex2int(t[1])) : '') + '</option>');
  }

  let h = '<div class=gpiot>' + _gpio_svg('Salida', 20, 1) +  _gpio_svg('Módulo / Desc', 60, 1) + _gpio_svg(' Bomba', 20, 1) + '</div>';
  pv1.S.forEach((_, i) => h += '<div class=gpio>' + _b10('S' + i + 'E', (i + 1), ' style="border:none;outline:none;" onclick={if(pv.hock)p("#@SM' + i + '2;")}') + '<div><select id=S' + i + 'T onchange=onSalidasTipo(' + i + ',value)>' + opt_s + '</select><br><input id=S' + i + 'L style=margin-top:3px;margin-bottom:10px; maxlength=24 oninput={pv1.S[' + i + '].l=value;_ubSalidas()} ></div>' + _b10('S' + i + 'B', '', ' onclick={pv1.S[' + i + '].bomba^=1;uSalidas()}') + '</div>' );
  h += '<hr><div class=div3 >' + _b('{firstChild.firstChild.innerHTML=="Calcelar"?window["r"+pvm.menuSistema]():clear_test()}', 'Clear Test', 'Cancel', '') + _b2l('probar()', 'Probar Salidas') + _b('window["s"+pvm.menuSistema]()', 'Guardar', 'Guardar', '') + '</div>';

  sistemaContent.innerHTML = h;
  uSalidas();
};

// -----------------------------------------------------------------------------

rBomba = () => rSistema('Bomba');

sBomba = () => {
  if (pv1.B.t0_offduración < 3000) pv1.B.t0_offduración = 3000;
  if (pv1.B.t0_offduración != pv.B.t0_offduración) setConfig('BT0' + pv1.B.t0_offduración);
  if (pv1.B.t1_onDelay != pv.B.t1_onDelay) setConfig('BT1' + pv1.B.t1_onDelay);
  if (pv1.B.t2_desactivando != pv.B.t2_desactivando) setConfig('BT2' + pv1.B.t2_desactivando);
  delete pv.B;
  setConfig('+'); rSistema('Bomba')
};

_ubBomba = () => {
  let m = pv.B, m1 = pv1.B;
  Cancel.style.visibility = Guardar.style.visibility = (((m1.t0_offduración != m.t0_offduración) || (m1.t1_onDelay != m.t1_onDelay) || (m1.t2_desactivando != m.t2_desactivando)) ? 'visible' : 'hidden');
};

uBomba = () => {
  BT0.value = pv1.B.t0_offduración / 1000;
  BT1.value = pv1.B.t1_onDelay / 1000;
  BT2.value = pv1.B.t2_desactivando / 1000;
  _ubBomba()
};

showBomba = () => {
  if (typeof pv.B === 'undefined') {
    tI = setInterval(() => {
    if (typeof pv.B === 'undefined') p('#@C;');
    else { clearInterval(tI); showBomba() }
    }, 3000);
    return;
  }
  if (typeof pv1.B === 'undefined') pv1.B = JSON.parse(JSON.stringify(pv.B)); // clone object

  let s = (i,a,b,v) => '<div><input id=BT' + i + ' type=number min=' + a + ' max=' + b + ' oninput={validity.valid||(value="");pv1.B.' + v + '=((value<min)?min:value)*1000;_ubBomba()} onkeypress={if(event.keyCode==13)blur()} onblur={value=((value<min)?min:value)} >s</div>',
  __s2l = t => '<svg viewBox="0 0 240 40"><rect fill=none /><foreignObject x=0 y=0 width=240 height=40><div>' + t + '</div></foreignObject></svg>';

  let h = '<h3>Bomba</h3><div class=div2><div>' + __s2l('Duración de apagado a encendido (min 3s, max 65s)') + '</div>' + s(0, 1, 65, 't0_offduración') + '</div><div class=div2 style=background-color:lightgrey><div>' + __s2l('Retraso de encendido <br> (min 1s, max 65s)') + '</div>' + s(1, 1, 65, 't1_onDelay') + '</div><div class=div2><div>' + __s2l('Retraso de apagado <br> (min 1s, max 65s)') + '</div>' + s(2, 1, 65, 't2_desactivando') + '</div>';

  h += '<hr><div class=div3 >' + _b('window["r"+pvm.menuSistema]()', 'Cancelar', 'Cancel', 'hidden') + _nbsp + _b('window["s"+pvm.menuSistema]()', 'Guardar', 'Guardar', 'hidden') + '</div>';

  sistemaContent.innerHTML = h;
  uBomba();
};
rSistema = s => {
  let h = 'hidden';
  pv1 = {};
  if (ge('Cancel')) Cancel.style.visibility = h;
  Guardar.style.visibility = h;
  if (pvm.menu == "Sistema") {
    if (pvm.menuSistema == s) window["show" + s]();
    else menuSistema(pvm.menuSistema)
  }
};

gSistema = s => { // show modal if changes and not saved
  if ((typeof pvm.menuSistema === 'undefined') || (!ge('Guardar'))) return 0;
  if ((pvm.menu != 'Sistema') || (pvm.menuSistema != s)) {  
    if (Guardar.style.visibility == 'visible') {
      let a = s;
      if (s == 'Admin') s = pvm.menuAdmin;
      hdmtGuardarTitle.innerHTML = s;
      _mN.onclick = () => { hG(); window["r" + s](); menu(pvm.menu) };
      _mS.onclick = () => { hG(); window["s" + s](); menu(pvm.menu) };
      _mV.onclick = () => { hG(); pvm.menu = 'Sistema'; pvm.menuSistema = a; /* menu('Sistema') */};
      hdmtGuardar.style.display = 'flex';
      return 1;
    }
  } else {
    if (ge('Guardar')) {
      if (Guardar.style.visibility == 'visible') return 1;
    }
  }
  return 0;
};

menuSistema = val => {
  let o = pvm.menuSistema;
  if (val == 'Wifi') {
    if (pvm.menuSistema != val) {
      if (typeof pve.mWifi === 'undefined') pve.mWifi = 1;
    } else {
      if ((++pve.mWifi) > 2) pve.mWifi = 1;
    }
  }

  pvm.menuSistema = val;
  if (gSistema(o)) return;
  Array.from(sistemaTab.children).forEach(v => { v.className = ((v.firstChild.firstChild.innerHTML == val) ? 'active' : '' )});
  window['show' + val]()
};

showSistema = () => { 
  let t = [];
  if (typeof pv.pic_version !== 'undefined') t.push('Salidas', 'Entradas', 'Bomba');    
  t.push('Wifi', 'Admin');
  let h = '<div class="tab tab' + (t.length < 4 ? 4 : t.length) + '" id=sistemaTab >'
  t.forEach(v => { 
    // FOR SRV START
    if (v == 'Bomba') {
      if ((pv.pic_version <= 500) || (!pv.B)) return;
    }
    // FOR SRV END
    h += _menu_b('menuSistema(\'' + v + '\')', v)
  });
  h += '</div><div class=tabcontent id=sistemaContent ></div>';
  mainContent.innerHTML = h;
  
  if (typeof pvm.menuSistema === 'undefined') pvm.menuSistema = 'Admin';
  menuSistema(pvm.menuSistema);
};
rTanque = () => rAjustes('Tanque');
sTanque = () => {
  pv1.T.forEach((m, i) => { 
    if (m == null) return;
    let t = pv.T[i];
    if (typeof t === 'undefined') {
      setConfig('T' + i + 'A' + m.modo);
      setConfig('S' + id2hex(m.s.id) + 'D' + m.s.duración)
    } else {
      if (m.modo != t.modo) setConfig('T' + i + 'A' + m.modo);
      if (m.s.duración != t.s.duración) setConfig('S' + id2hex(m.s.id) + 'D' + m.s.duración);
    }
  });
  delete pv.T; setConfig('+'); rAjustes('Tanque')
};

_ubTanque = () => {
  let showBoton = 0;
  pv1.T.forEach((m, i) => {
    if (m) {
      let t = pv.T[i];
      if ((typeof t === 'undefined') || (m.modo != t.modo) || (m.s.duración != t.s.duración)) showBoton = 1;
    }
  });
  Cancel.style.visibility = AjustesGuardar.style.visibility = (showBoton ? 'visible' : 'hidden');;
};

uTanqueAuto = id => {
  let e = ge('T' + id + 'A'), m = pv1.T[id].modo;
  e.firstChild.firstChild.innerHTML = m ? 'Automático' : 'Manual';
  e.style.backgroundColor = m ? 'lightgreen' : 'red';
};

toggleTanqueAuto = id => {
  if (pv1.T[id].tipo_flotante == 0) return;
  pv1.T[id].modo ^= 1;
  uTanqueAuto(id);
  _ubTanque();
};

uTanque = () => {
  if (!pv1.T) return showAjustes();
  pv1.T.forEach(m => { if (m) { uTanqueAuto(m.id);  ge('T' + m.id + 'D').value = m.s.duración; }});
  _ubTanque();
};

showTanque = () => {
  if (typeof pv.T === 'undefined') return;
  if (!pv1.T) pv1.T = JSON.parse(JSON.stringify(pv.T)); // clone object

  let h = '<div class=div3>' + _div3_svg('Tanque', 1) +  _div3_svg('Modo', 1) + _div3_svg('Duración', 1) + '</div>';
  pv1.T.forEach(m => {
    if (m) {
      let i = m.id;
      h += '<div class=div3>' + _div3_svg_2l((m.s.l == '') ? i + 1 : m.s.l) + _b('toggleTanqueAuto(' + i + ')', '', 'T' + i + 'A') + '<div><input id=T' + id2hex(i) + 'D type=number min=1 max=9999 oninput={validity.valid||(value="");pv1.T[' + i + '].s.duración=value;_ubTanque()} onkeypress={if(event.keyCode==13)blur()} onblur={value=((value<min)?min:value)} >minuto(s)</div></div>';
    }
  });

  ajustesContent.innerHTML = h;
  uTanque();
};let pvWifi, wifi_alert = true;
// 2026-03-18 TODO : hidromotic.com change wifi dynamic to static and save, chi/chi not reconnect!

rWifi = () => { pvWifi = void 0; pve.mWifi = 1; rSistema('Wifi') };
sWifi = () => {
  if (!pve.info) return;
  let wifi = {}, sta = {}, m = pve.info.wifi.sta, m1 = pvWifi.sta;
    sta.enable = true;
    if (m1.dhcp != m.dhcp) {
      if (m1.dhcp != "Static") {
        sta.ip = sta.gw = sta.netmask = "";
      }
    }
    if (m1.dhcp == "Static") {
      switch (m1.IP4) {
        case "":
        case m1.GW4: _showModal("CONFLICT", "INVALID IP, conflicto con router gateway"); break;
        default:
          sta.gw = m1.gw;
          sta.ip = m1.IP3 + m1.IP4;
          sta.netmask = "255.255.255.0";
          break;
      }
    }
  if (Object.keys(sta).length) wifi.sta = sta;
  if (Object.keys(wifi).length) {
    if (ws) {
      wifi_alert = true;
      // Cancel.style.visibility = Guardar.style.visibility = 'hidden';
      pve.mWifi = 1;
      delete pve.info;
      pvWifi = void 0;
      // p("e.W0"); // disconnect wifi
      ws.send('{"id":300,"src":"me","method":"Config.Set","params":{"config":{"mqtt":{"enable":true},"wifi":' + JSON.stringify(wifi) + '},"save":true,"try_once":false,"reboot":true}}');
      // p("e.W1"); // reconnect wifi

      pvm = {};
      mainTab.style.display = 'none';
      mainContent.innerHTML = 'Sistema reconectando, espera ...';

      switch (location.host) {
        // FOR SRV START
        case 'hidromotic.com':          // hidromotic srv
          setTimeout(() =>showMain() /*menu('Info')*/ , 10000);
          break;
        // FOR SRV END
      }
    }
  }
  // rSistema('Wifi')
};

uWB = () => {
  let m = pve.info.wifi.sta, m1 = pvWifi.sta;
  Cancel.style.visibility = Guardar.style.visibility = (((m.ssid != m1.ssid) | (m.pass != m1.pass) | (m.dhcp != m1.dhcp) | (m.IP4 != m1.IP4)) ? 'visible' : 'hidden');
};

onIPblur = () => {
  if (IP.value == pvWifi.sta.GW4) {
    _showModal('CONFLICT', 'INVALID IP, conflicto con router gateway');
    IP.focus();
  }
};

onIP = () => { pvWifi.sta.IP4 = IP.value; uWB() };

onDHCP = () => {
  pvWifi.sta.dhcp = DHCP.value;
  if (DHCP.value != 'Static') {
    showIP.style.display = 'none';
  } else {
    showIP.style.display = '';
    IP.focus();
  }
  uWB();
};

onSSID = () => {
  let m = pve.info.wifi.sta, m1 = pvWifi.sta;
  if (ge('sta_err')) sta_err.style.display = 'none';
  showOtro.style.display = showPass.style.display = showDHCP.style.display = showIP.style.display = 'none';
  
  let v = staSSID.value;
  delete m1.connected;
  if (v == 'Ninguna') {
    m1.ssid = m1.ip = m1.gw = m1.netmask = '';
    m1.pass = void 0;
    m1.dhcp = 'Dynamic';
    uWB();
    return; 
  }

  showPass.style.display = '';
  if (v == 'Otro') {
    m1.ssid = v = otro.value;
    showOtro.style.display = '';
  }

  if (v == m.ssid) {
    if (ge('sta_err')) sta_err.style.display = '';
    if (v != pvWifi.sta.ssid) {
      m1.ssid = v;
      m1.pass = m.pass;
      m1.dhcp = m.dhcp;
      m1.ip = m.ip;
      m1.gw = m.gw;      
    }
    m1.connected = m.connected;
    staPassChecked.checked = pvWifi.sta.pass_type;
    staPass.type = (staPassChecked.checked ? 'text' : 'password');
    staPass.value = m1.pass;
    if (m1.connected == 'conectado') {
      if (m.gw != '') {
        showDHCP.style.display = '';
        DHCP.value = m1.dhcp;
        onDHCP();
      }
    }
  } else {
    m1.ssid = v;
    m1.pass = staPass.value = '';
    staPass.type = 'text';
    pvWifi.sta.pass_type = staPassChecked.checked = true;
    staPass.focus();
    m1.dhcp = DHCP.value = 'Dynamic';
    m1.gw = m1.ip = '';
  }
  uWB();
};

let pWifi = '';
onWifi = v => {pWifi = v; if (v == 'Wifi') { if (pve.mWifi != 2) {pve.mWifi = 2; showWifi()}}};

showWifi = () => {
  if (typeof pve.mWifi === 'undefined') pve.mWifi = 1;
  let m2 = pve.mWifi;
  if (m2 > 2) m2 = pve.mWifi = 1;
  if (typeof pve.info === 'undefined') {
    p('e'); sistemaContent.innerHTML = 'Espera ...';
    return;
  }

  if (pve.info.wifi.sta.ssid == '') m2 = 2;
  else if (pWifi != 'Wifi') {
    if (m2 == 2) {
      sistemaContent.innerHTML = '<label for=wifiClave ><h3>Clave</h3></label><input id=wifiClave name=wifiClave oninput=onWifi(value) >';
      sistemaContent.children[1].focus();
      pve.mWifi = 3;
      return;
    } else pve.mWifi = 1;
  }
  
  let _static_ip = () => {
    let _ip = pvWifi.sta.ip;
    if (_ip != '') {
      let _g = _ip.lastIndexOf('.') + 1;
      pvWifi.sta.IP3 = _ip.substr(0, _g);
      pve.info.wifi.sta.IP4 = pvWifi.sta.IP4 = _ip.substr(_g);
      pve.info.wifi.sta.GW4 = pvWifi.sta.GW4 = pvWifi.sta.gw.substr(_g);
    } else {
      pvWifi.sta.IP3 = '';
      pve.info.wifi.sta.IP4 = pvWifi.sta.IP4 = 250;
    }
  };

  if (typeof pvWifi === 'undefined') {
    pvWifi = JSON.parse(JSON.stringify(pve.info.wifi)); // clone object
    _static_ip();
  } else {
    let m = pve.info.wifi.sta, m1 = pvWifi.sta;
    if (m1.ssid == m.ssid) {
      if (m1.connected != m.connected) {
        m1.connected = m.connected;
        m1.ip = m.ip;
        m1.gw = m.gw;
        _static_ip();
      }
    }
  }

  let h, n = pvWifi.sta,
    _h1 = (t, t2) => '<div class=wifi><div>' + t + '</div><div>:</div><div>' + t2 + '</div></div>',
    _h2 = (t, t2) => '<div class=wifi><div><h3>' + t + '</h3></div><div>:</div><div><h3>' + t2 + '<h3></div></div>',
    r = (t, t2, s) => '<div' + (s ? (' id=show' + s) : '')  + '><h3>' + t + '</h3><div>' + t2 + '</div></div>';

  let d = pve.info.wifi.sta, de;
  if (wifi_alert) {
    let df = e => {
      de = e;
      m2 = pve.mWifi = 2;
      pWifi = 'Wifi';
      wifi_alert = false;
    };
    switch (d.reason) {
      case 201: df('Wifi SSID no existe'); break;
      case 202: df('Wifi Contraseña incorrecta'); break;
    }
  }

  let wifiBoton = '<hr><div class=div3>' + _b('rWifi()', 'Cancelar', 'Cancel', 'hidden') + (pve.AP ? _b2l('pve.scanwifi=1;p("e.W");showWifi()', 'Buscar Redes') : _nbsp) + _b('sWifi()', 'Guardar', 'Guardar', 'hidden') + '</div>';

  switch (m2) {
    case 1: // mostra data simple
      h = _h1('Red Actual', d.ssid);
      if (d.connected == 'conectado')
        h += _h1('DHCP', d.dhcp) + _h1('GW', d.gw) + _h1('IP', d.ip) + _h1('Nivel de señal', _rssiToStrength(d.rssi) + '%') + _h1('Tiempo conectado', d.routertime + ' s');
      else if (d.ssid != '')
        h += _h1('Estado', d.connected.toUpperCase()) + _h1('código', d.reason) + _h1('reintentos', d.retry);

      h += '<hr><div class=div3>' + _nbsp + _nbsp + _b('p("e")', 'Refrescar');
      sistemaContent.innerHTML = h;
      break;

    case 2:
      if (pve.AP) { // modo AP
        if (typeof pve.wifi === 'undefined') {
          if (pve.scanwifi != 1) {
            pve.scanwifi = 1;
            p('e.W');
          }
        }

        h = r('Red' + ((pve.scanwifi == 1) ? ' ("Escaneando wifi!")' : ((typeof pve.wifi === 'undefined') ? ' (No se detectaron redes)' : '' )), '<select id=staSSID style=width80%; onchange=onSSID() ></select>') + r('&nbsp;', '<input id=otro type=text style=width80% oninput={if(staSSID.value="Otro")pvWifi.sta.ssid=value;uWB()} onfocus=this.select() placeholder="otro ssid?">', 'Otro') + r('Pass','<input id=staPass type=text placeholder=clave oninput={pvWifi.sta.pass=value;uWB()} onkeypress={if(event.keyCode==13)blur()} style=text-align:right;width=20%><input id=staPassChecked type=checkbox onclick={pvWifi.sta.pass_type=checked;staPass.type=(checked?"text":"password");staPass.focus()} checked>', 'Pass') + '<br>' + r('DHCP', '<select id=DHCP onchange=onDHCP() ><option value=Dynamic >Dynamic</option><option value=Static >Static</option></select>', 'DHCP') + '<br>' + r('IP', '<span id=spanIP >' + ((typeof pvWifi.sta.IP3 != 'undefined') ? pvWifi.sta.IP3 : '') + '</span><input id=IP type=number min=1 max=254 oninput={validity.valid||(value="");onIP()} onblur=onIPblur() placeholder=?' + ((typeof pvWifi.sta.IP4 != 'undefined') ? (' value=' + pvWifi.sta.IP4) : '') + '>', 'IP') + '<br>';

        if (pvWifi.sta.ssid == pve.info.wifi.sta.ssid) {
          switch (d.reason) {
            case 201: 
              h += '<h3 id=sta_err>Wifi SSID no existe</h3>';
              break;
            case 202:
              h += '<h3 id=sta_err>Wifi Contraseña incorrecta</h3>';
              break;

            default:
              h += '<h3 id=sta_err>' + d.connected + '</h3>';
              break;
          }
        }
        sistemaContent.innerHTML = h + wifiBoton + '</div>';
        switch (d.reason) {
          case 201: 
            if (staSSID.value == 'Otro') otro.focus();
            else staSSID.focus();
            break;
          case 202: staPass.focus(); break;
        }
        staPassChecked.checked = pvWifi.sta.pass_type;
        staPass.type=(staPassChecked.checked ? 'text' : 'password');

        h = '<option value=Ninguna >Ninguna</option>';
        if (pve.wifi) {
          pve.wifi.sort((a, b) => b.rssi - a.rssi);
          let t = [];

          let existSSID = e => {
            for (let w of t) { if (w.ssid == e.ssid) return true }
            return false;
          };
          let opt = v => '<option value="' + v.ssid + '" auth=' + v.auth + ' >' + (v.auth > 0 ? '🔒 ' : '🔓 ') + v.ssid + ' (' + _rssiToStrength(v.rssi) + '%)</option>';          
          for (let v of pve.wifi) {
            if (!existSSID(v)) {
              t.push(v);
              h += opt(v);
            }
          }
        }
        h += '<option value=Otro >Otro</option>';

        staSSID.innerHTML = h;
        let sta = pvWifi.sta;        
        staSSID.value = ((sta.ssid == '') ? 'Ninguna' : sta.ssid);
        if (staSSID.selectedIndex == -1) {
          staSSID.value = 'Otro';
          otro.value = sta.ssid;
          showOtro.style.display = '';
        }

        onSSID(staSSID);
        if (typeof de !== 'undefined') _showModal('Wifi Error', de);
      } else { // none AP
        h = _h2('Red Actual', n.ssid) + _h2('Conectado', (n.connected == 'conectado') ? 'SI' : 'NO') + '<br>' + r('DHCP', '<select id=DHCP onchange=onDHCP()><option value=Dynamic >Dynamic</option><option value=Static >Static</option></select>', 'DHCP') + '<br>' + r('IP', '<span id=spanIP >' + pvWifi.sta.IP3 + '</span><input id=IP type=number min=1 max=254 oninput={validity.valid||(value="");onIP()} onblur=onIPblur() placeholder=? value=' + pvWifi.sta.IP4 + '>', 'IP') + wifiBoton + '</div>';        
        sistemaContent.innerHTML = h;
        DHCP.value = pvWifi.sta.dhcp;
        onDHCP();
      }
      break;
  }
};
rZona = () => rAjustes('Zona');
sZona = () => {
  pv1.Z.forEach((m, i) => { if (m) { if ((typeof pv.Z[i] === 'undefined') || (m.s.duración != pv.Z[i].s.duración)) setConfig('S' + id2hex(m.s.id) + 'D' + m.s.duración) }});
  delete pv.Z; setConfig('+'); rAjustes('Zona')
};

_ubZona = () => {
  let showBoton = 0;
  pv1.Z.forEach((m, i) => {
    if (m) { if ((typeof pv.Z[i] === 'undefined') || (m.s.duración != pv.Z[i].s.duración)) showBoton = 1 }});
  Cancel.style.visibility = AjustesGuardar.style.visibility = (showBoton ? 'visible' : 'hidden');
};

uZona = () => {
  if (typeof pv1.Z === 'undefined') return showAjustes();
  pv1.Z.forEach(m => {if (m) ge('Z' + id2hex(m.id) + 'D').value = m.s.duración });
  _ubZona()
};

showZona = () => {
  if (typeof pv.Z === 'undefined') return;
  if (typeof pv1.Z === 'undefined') pv1.Z = JSON.parse(JSON.stringify(pv.Z)); // clone object

  let h = '<div class=div2>' + _div2_svg('Zona', 50, 1) + _div2_svg('Duración', 50, 1) + '</div>';
  pv1.Z.forEach(m => { if (m) h += '<div class=div2>' + _div2_svg(((m.s.l == '') ? m.id + 1 : m.s.l), 50) + '<div><input id=Z' + id2hex(m.id) + 'D type=number min=1 max=9999 oninput={validity.valid||(value="");pv1.Z[' + m.id + '].s.duración=((value<min)?min:value);_ubZona()} onkeypress={if(event.keyCode==13)blur()} onblur={value=((value<min)?min:value)} >minuto(s)</div></div>'});
 
  ajustesContent.innerHTML = h;
  uZona()
};