/* lume-launcher · módulo de idiomas: inglês, espanhol e português do Brasil.
   Regras: os 3 dicionários têm EXATAMENTE as mesmas chaves (tools/check-i18n.js confere), e os textos são curtos,
   porque a tela de 3,5" tem pouca largura (o espanhol e o inglês costumam ser mais longos que o português).
   No app real: um arquivo de texto por idioma (ex.: i18n/pt-BR.toml), carregado na hora. */
(function () {
  'use strict';
  const Lume = (window.Lume = window.Lume || {});
  const dict = {
    'pt-BR': {
      fav: 'Favoritos', set: 'Configurações', setsub: 'Ajustes do aparelho', games: 'jogos', files: 'Arquivos', shots: 'Capturas', imgs: 'imagens',
      sel: 'Selecionar', back: 'Voltar', move: 'Navegar', view: 'Ver', openf: 'Abrir', up: 'Subir', adj: '◀ ▶ para ajustar', open: 'A para abrir',
      play: 'Iniciar', state: 'Iniciar de um save state', nosave: 'sem saves', favAdd: 'Incluir em favoritos', favDel: 'Remover dos favoritos',
      emu: 'Emulador', aspect: 'Aspecto', coreAspect: 'Do core', shader: 'Shader',
      search: 'Buscar', noresults: 'Nenhum jogo encontrado.', keySpace: 'Espaço', keyClear: 'Limpar',
      console: 'Console', consoleOpts: 'Opções do console', clearGames: 'Limpar opções dos jogos', cleared: 'Opções dos jogos limpas', inherit: 'Padrão', otherCore: 'em outro core',
      sh_none: 'Nenhum', sh_scanlines: 'Scanlines', sh_crt: 'CRT', sh_lcd: 'LCD', sh_sharp: 'Pixel nítido',
      lowbatt: 'Bateria fraca',
      added: 'Adicionado aos favoritos', removed: 'Removido dos favoritos', nofavs: 'Nenhum favorito ainda.\nUse “Incluir em favoritos” no menu de um jogo.',
      slot: 'Slot', auto: 'Auto', launching: 'Iniciando', launchNote: '(simulado) runner → emulador → volta ao launcher ao fechar',
      noshots: 'Nenhuma captura ainda.', emptyDir: 'Pasta vazia', items: 'itens', unsup: 'Só abre imagens e arquivos .txt',
      badimg: 'Não foi possível abrir esta imagem', toobig: 'Arquivo grande demais para abrir (acima de 256 KB).',
      lite: 'Tela', on: 'Ligado', off: 'Desligado', liteNote: 'Sem animações nem transparência, para aparelhos fracos.',
      wifi: 'Wi-Fi', bt: 'Bluetooth', lang: 'Idioma', theme: 'Tema', vol: 'Volume', bri: 'Brilho', system: 'Sistema', power: 'Desligar o aparelho',
      'th_material-escuro': 'Escuro', 'th_material-claro': 'Claro',
      connected: 'Conectado', disconnected: 'Desconectado', adapter: 'Adaptador USB', conn: 'Conectado a', disc: 'Desconectado de', netq: 'Redes próximas', devq: 'Dispositivos',
      model: 'Modelo', cpu: 'CPU', mem: 'Memória', lmem: 'Launcher (RSS)', storage: 'Cartão SD', simNote: 'Valores simulados.',
      powerAsk: 'O aparelho será desligado.', yes: 'Desligar', no: 'Cancelar', off1: 'Desligando…', off2: '(simulado) pressione qualquer tecla para ligar',
      card: 'Cartão', sleep: 'Suspender', sysMenu: 'Menu do sistema', reboot: 'Reiniciar', rebootTitle: 'Reiniciar o aparelho', rebootAsk: 'O aparelho será reiniciado.', reboot1: 'Reiniciando…', menuHint: 'Menu', hintTap: '(toque): Menu do sistema', hintBri: ': Brilho', gamesRow: 'Games', refresh: 'Atualizar listas', refreshed: 'Listas atualizadas', sleep1: 'Suspenso', sleep2: '(simulado) pressione qualquer tecla para acordar',
      free: 'Espaço livre', lastTrim: 'Última otimização', lastCheck: 'Última verificação', bootN: 'boot', never: 'nunca',
      trimNow: 'Otimizar agora', checkNext: 'Verificar no próximo boot', trimming: 'Otimizando…', freed: 'liberados', trimFail: 'Cartão sem suporte', checkSet: '✓ Agendada',
      reported: 'Falha registrada',
      resetLearn: 'Recomeçar o aprendizado', resetAsk: 'O limite deste aparelho será apagado.', yesNo: 'Sim', resetDone: 'Aprendizado recomeçado',
      clock: 'Mostrar relógio', settime: 'Acertar a hora', clockNever: 'A hora ainda não foi acertada: o relógio só aparece depois de acertar.',
      fDate: 'Data', fTime: 'Hora', fY: 'Ano', fMo: 'Mês', fD: 'Dia', fH: 'Hora', fMi: 'Min', timeNote: '▲▼ mudam o valor, ◀▶ trocam de campo, L1/R1 saltam.', chg: 'Alterar', fld: 'Campo', apply: 'Acertar', timeDone: 'Hora acertada'
    },
    'en': {
      fav: 'Favorites', set: 'Settings', setsub: 'Device settings', games: 'games', files: 'Files', shots: 'Screenshots', imgs: 'images',
      sel: 'Select', back: 'Back', move: 'Move', view: 'View', openf: 'Open', up: 'Up', adj: '◀ ▶ to adjust', open: 'A to open',
      play: 'Start', state: 'Start from save state', nosave: 'no saves', favAdd: 'Add to favorites', favDel: 'Remove from favorites',
      emu: 'Emulator', aspect: 'Aspect', coreAspect: 'Core', shader: 'Shader',
      search: 'Search', noresults: 'No games found.', keySpace: 'Space', keyClear: 'Clear',
      console: 'Console', consoleOpts: 'Console options', clearGames: 'Clear game options', cleared: 'Game options cleared', inherit: 'Default', otherCore: 'in another core',
      sh_none: 'None', sh_scanlines: 'Scanlines', sh_crt: 'CRT', sh_lcd: 'LCD', sh_sharp: 'Sharp pixels',
      lowbatt: 'Low battery',
      added: 'Added to favorites', removed: 'Removed from favorites', nofavs: 'No favorites yet.\nUse “Add to favorites” in a game’s menu.',
      slot: 'Slot', auto: 'Auto', launching: 'Starting', launchNote: '(simulated) runner → emulator → back to launcher on exit',
      noshots: 'No screenshots yet.', emptyDir: 'Empty folder', items: 'items', unsup: 'Only images and .txt files open',
      badimg: 'This image could not be opened', toobig: 'File too large to open (over 256 KB).',
      lite: 'Display', on: 'On', off: 'Off', liteNote: 'No animations or transparency, for low-end devices.',
      wifi: 'Wi-Fi', bt: 'Bluetooth', lang: 'Language', theme: 'Theme', vol: 'Volume', bri: 'Brightness', system: 'System', power: 'Power off',
      'th_material-escuro': 'Dark', 'th_material-claro': 'Light',
      connected: 'Connected', disconnected: 'Disconnected', adapter: 'USB adapter', conn: 'Connected to', disc: 'Disconnected from', netq: 'Nearby networks', devq: 'Devices',
      model: 'Model', cpu: 'CPU', mem: 'Memory', lmem: 'Launcher (RSS)', storage: 'SD card', simNote: 'Simulated values.',
      powerAsk: 'The device will be turned off.', yes: 'Power off', no: 'Cancel', off1: 'Shutting down…', off2: '(simulated) press any key to power on',
      card: 'Card', sleep: 'Suspend', sysMenu: 'System menu', reboot: 'Restart', rebootTitle: 'Restart the device', rebootAsk: 'The device will restart.', reboot1: 'Restarting…', menuHint: 'Menu', hintTap: '(tap): System menu', hintBri: ': Brightness', gamesRow: 'Games', refresh: 'Refresh lists', refreshed: 'Lists refreshed', sleep1: 'Suspended', sleep2: '(simulated) press any key to wake',
      free: 'Free space', lastTrim: 'Last optimization', lastCheck: 'Last check', bootN: 'boot', never: 'never',
      trimNow: 'Optimize now', checkNext: 'Check on next boot', trimming: 'Optimizing…', freed: 'freed', trimFail: 'Card not supported', checkSet: '✓ Scheduled',
      reported: 'Failure logged',
      resetLearn: 'Restart learning', resetAsk: 'This device’s limit will be erased.', yesNo: 'Yes', resetDone: 'Learning restarted',
      clock: 'Show clock', settime: 'Set the time', clockNever: 'The time has not been set yet: the clock appears only after it is set.',
      fDate: 'Date', fTime: 'Time', fY: 'Year', fMo: 'Month', fD: 'Day', fH: 'Hour', fMi: 'Min', timeNote: '▲▼ change the value, ◀▶ switch field, L1/R1 jump.', chg: 'Change', fld: 'Field', apply: 'Set time', timeDone: 'Time set'
    },
    'es': {
      fav: 'Favoritos', set: 'Ajustes', setsub: 'Ajustes del equipo', games: 'juegos', files: 'Archivos', shots: 'Capturas', imgs: 'imágenes',
      sel: 'Seleccionar', back: 'Volver', move: 'Navegar', view: 'Ver', openf: 'Abrir', up: 'Subir', adj: '◀ ▶ para ajustar', open: 'A para abrir',
      play: 'Iniciar', state: 'Iniciar desde save state', nosave: 'sin saves', favAdd: 'Añadir a favoritos', favDel: 'Quitar de favoritos',
      emu: 'Emulador', aspect: 'Aspecto', coreAspect: 'Del core', shader: 'Shader',
      search: 'Buscar', noresults: 'Ningún juego encontrado.', keySpace: 'Espacio', keyClear: 'Borrar',
      console: 'Consola', consoleOpts: 'Opciones de la consola', clearGames: 'Borrar opciones de juegos', cleared: 'Opciones de juegos borradas', inherit: 'Predet.', otherCore: 'en otro core',
      sh_none: 'Ninguno', sh_scanlines: 'Scanlines', sh_crt: 'CRT', sh_lcd: 'LCD', sh_sharp: 'Píxel nítido',
      lowbatt: 'Batería baja',
      added: 'Añadido a favoritos', removed: 'Quitado de favoritos', nofavs: 'Aún no hay favoritos.\nUsa “Añadir a favoritos” en el menú de un juego.',
      slot: 'Slot', auto: 'Auto', launching: 'Iniciando', launchNote: '(simulado) runner → emulador → vuelve al launcher al cerrar',
      noshots: 'Aún no hay capturas.', emptyDir: 'Carpeta vacía', items: 'elementos', unsup: 'Solo abre imágenes y archivos .txt',
      badimg: 'No se pudo abrir esta imagen', toobig: 'Archivo demasiado grande para abrir (más de 256 KB).',
      lite: 'Pantalla', on: 'Activado', off: 'Desactivado', liteNote: 'Sin animaciones ni transparencia, para equipos lentos.',
      wifi: 'Wi-Fi', bt: 'Bluetooth', lang: 'Idioma', theme: 'Tema', vol: 'Volumen', bri: 'Brillo', system: 'Sistema', power: 'Apagar el equipo',
      'th_material-escuro': 'Oscuro', 'th_material-claro': 'Claro',
      connected: 'Conectado', disconnected: 'Desconectado', adapter: 'Adaptador USB', conn: 'Conectado a', disc: 'Desconectado de', netq: 'Redes cercanas', devq: 'Dispositivos',
      model: 'Modelo', cpu: 'CPU', mem: 'Memoria', lmem: 'Launcher (RSS)', storage: 'Tarjeta SD', simNote: 'Valores simulados.',
      powerAsk: 'El equipo se apagará.', yes: 'Apagar', no: 'Cancelar', off1: 'Apagando…', off2: '(simulado) pulsa cualquier tecla para encender',
      card: 'Tarjeta', sleep: 'Suspender', sysMenu: 'Menú del sistema', reboot: 'Reiniciar', rebootTitle: 'Reiniciar el equipo', rebootAsk: 'El equipo se reiniciará.', reboot1: 'Reiniciando…', menuHint: 'Menú', hintTap: '(toque): Menú del sistema', hintBri: ': Brillo', gamesRow: 'Games', refresh: 'Actualizar listas', refreshed: 'Listas actualizadas', sleep1: 'Suspendido', sleep2: '(simulado) pulsa cualquier tecla para despertar',
      free: 'Espacio libre', lastTrim: 'Última optimización', lastCheck: 'Última verificación', bootN: 'arranque', never: 'nunca',
      trimNow: 'Optimizar ahora', checkNext: 'Verificar al arrancar', trimming: 'Optimizando…', freed: 'liberados', trimFail: 'Tarjeta no compatible', checkSet: '✓ Pedida',
      reported: 'Fallo registrado',
      resetLearn: 'Reiniciar el aprendizaje', resetAsk: 'Se borrará el límite de este equipo.', yesNo: 'Sí', resetDone: 'Aprendizaje reiniciado',
      clock: 'Mostrar reloj', settime: 'Ajustar la hora', clockNever: 'La hora aún no se ha ajustado: el reloj solo aparece después de ajustarla.',
      fDate: 'Fecha', fTime: 'Hora', fY: 'Año', fMo: 'Mes', fD: 'Día', fH: 'Hora', fMi: 'Min', timeNote: '▲▼ cambian el valor, ◀▶ cambian de campo, L1/R1 saltan.', chg: 'Cambiar', fld: 'Campo', apply: 'Ajustar', timeDone: 'Hora ajustada'
    }
  };
  Lume.i18n = {
    langs: [['pt-BR', 'Português (Brasil)'], ['en', 'English'], ['es', 'Español']],
    dict,
    t: (lang, key) => ((dict[lang] || dict['pt-BR'])[key]) || key
  };
})();
