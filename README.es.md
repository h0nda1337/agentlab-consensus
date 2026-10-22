# AgentLab Consensus: reparación cooperativa

El modo `repair` permite a Dars, Rade y Miso trabajar sobre software real.
Dars propone implementación, Rade revisa corrección y Miso comprueba pruebas y
casos límite. Los tres pueden inspeccionar, proponer cambios y ejecutar comandos.
Los roles orientan su trabajo; ninguno tiene una misión oculta ni busca culpables.
Las propuestas rotan entre los tres y todos reciben la misma evidencia compartida.

## Empezar con el asistente

Necesitas Python 3.11 o posterior y modelos servidos con llama.cpp que admitan
chat y gramática GBNF. No se incluyen pesos de modelos ni dependencias Python.

```powershell
python .\agentlab.py setup
```

En Windows también puedes abrir `Setup.cmd` con doble clic. El asistente guía
cuatro pasos: nombres del equipo, conexión de modelos, entorno y revisión final.
Puedes conectar servidores existentes o elegir tus GGUF para cargarlos por turnos.
Selecciona la plantilla nativa del GGUF o Gemma 2 según el modelo de cada agente.
Los selectores de archivos de la interfaz evitan tener que escribir rutas.

Enter conserva los valores actuales. Ctrl+C sale sin guardar el borrador. Al guardar
se conservan ajustes adicionales y se respaldan los archivos anteriores. La
comprobación distingue entre configuración guardada y requisitos pendientes; no
inicia modelos. Preparar WSL es una opción explícita porque descarga Debian y paquetes.

Sin configuración, `python agentlab.py` abre el asistente automáticamente. En
Linux/macOS puedes usar el mismo asistente para carpetas y servidores existentes.

## Interfaz para Windows y Visual Studio 2019

Abre `Start-Desktop.cmd` para usar la interfaz. Incluye asistente visual, nombres
editables, selección de GGUF, comprobación de conexiones, preparación de WSL,
formulario de reparación y actividad en vivo con propuestas, votos y pruebas.
El botón **Elegir Python** permite seleccionar el intérprete si no se detecta.

Para editar o compilar, abre `desktop/AgentLab.Desktop.sln` en Visual Studio 2019
o posterior con la carga **Desarrollo de escritorio de .NET** y elige Release.
Usa WPF y .NET Framework 4.8. Las referencias de compilación se restauran por NuGet.
El lanzador también compila automáticamente si aún no existe el ejecutable.
[Documentación de Microsoft para WPF y VS 2019](https://learn.microsoft.com/en-us/dotnet/desktop/wpf/get-started/walkthrough-my-first-wpf-desktop-application).

La [versión portátil para Windows](https://github.com/h0nda1337/agentlab-consensus/releases)
incluye la interfaz compilada: extrae todo el ZIP y abre `Start-Desktop.cmd`.
Sigue necesitando Python 3.11+ y tus modelos; no requiere Visual Studio para ejecutarse.

**Solicitar parada** conserva la sesión y espera a que termine la respuesta del
modelo o comando actual antes de continuar con el cierre. Puede tardar varios
minutos. La interfaz solo anuncia verificación cuando pasan las pruebas y los tres
agentes aprueban el resultado. Para comprobar la aplicación sin abrir ventanas:

```powershell
.\Build-Desktop.ps1 -SelfTest
```

## Cambiar nombres fácilmente

```powershell
python .\agentlab.py agents names Atlas Iris Nova
python .\agentlab.py agents list
python .\agentlab.py agents rename Atlas Atenea
```

El orden de `names` es implementación, revisión y pruebas. También puedes editar
`display_name` dentro de cada agente de `config.json`. Cambia el nombre visible y
el que recibe el modelo, conservando el identificador interno, su endpoint y su rol.
No es necesario editar código ni renombrar carpetas. Los nombres deben ser distintos.

## Reparar una carpeta

Desde PowerShell en la carpeta del repositorio:

```powershell
python .\agentlab.py folder "D:/mi-proyecto" --task "Describe el fallo que deben corregir" --test "python -m unittest discover -s tests -v" --apply
```

`--test` es el comando del supervisor que debe pasar antes de declarar el trabajo
terminado. Puede ser `npm test`, `pytest`, un script de validación o una comprobación
del sistema. Usa un comando que compruebe el resultado real del objetivo.

Si eliges carga local por turnos, el asistente activa `coding.load_on_demand`: carga el modelo de
quien está interviniendo y libera el servidor que inició para el turno anterior.
Así pueden participar los tres sin quedar residentes junto al WSL. Los tres siguen
compartiendo la misma discusión y todos votan. El arranque usa un perfil conservador:
8 capas GPU cuando hay margen, o CPU con menos memoria disponible. Puede ser lento
con estos modelos. No hace falta arrancar los
tres con `start_servers.ps1` antes de reparar. Solo cierra servidores que inició
esta sesión, comprobando token, PID y fecha de inicio; deja otros modelos abiertos.
Si quieres usar servidores permanentes o endpoints externos, configura
`coding.load_on_demand` como `false` y arráncalos por separado.

Se crea una copia de los archivos actuales, incluidos cambios sin commit. El equipo
lee, busca, edita y prueba en esa copia. Se omiten `.git`, entornos virtuales,
`node_modules`, cachés, enlaces y junctions. Instala dependencias en la copia si son
necesarias. Esta copia **no es un sandbox del sistema operativo**: sus comandos se
ejecutan con los permisos de tu usuario de Windows. Para trabajar en Linux utiliza WSL.

`--apply` publica los cambios solamente cuando pasan las pruebas y los tres aprueban
el cierre. Comprueba que los archivos originales afectados no hayan cambiado desde
el inicio; si detecta un conflicto, conserva la copia y no sobreescribe el trabajo
del usuario. Guarda los originales afectados en `backups` dentro de la sesión. Si
falla una copia durante la publicación intenta restaurar los archivos ya escritos.
Sin `--apply`, los cambios verificados se conservan en `workspace` para inspección.
La publicación no es una transacción resistente a apagones ni una exclusión frente
a editores externos que escriban justo durante la publicación.

Una demostración pequeña, intencionalmente defectuosa:

```powershell
python .\repair.py folder .\examples\repair-demo --task "Corrige add para sumar números positivos y negativos sin debilitar las pruebas" --test "python -m unittest -v"
```

## WSL dedicado con acceso completo

```powershell
.\setup_repair_wsl.ps1
wsl.exe -d AgentLab-Repair -u root --cd /workspace
```

El instalador prepara un Debian nuevo llamado `AgentLab-Repair`, con Python, Git,
curl y herramientas de compilación. No clona los datos de Debian ni DarsVault.
Por defecto guarda su disco en `%LOCALAPPDATA%\AgentLab\WSL\AgentLab-Repair`.
Puedes elegir otro disco con `-Location 'C:\WSL\AgentLab-Repair'`; exige 4 GB libres.
Nunca reemplaza ni desregistra automáticamente una distribución existente.

Clona o copia el proyecto a `/workspace` desde esa consola. También puedes preparar
un proyecto en otra ruta Linux y seleccionarla con `--path`. Después, desde Windows:

```powershell
python .\agentlab.py wsl --path /workspace/mi-proyecto --task "Corrige el fallo y añade una prueba de regresión" --test "python3 -m unittest discover -s tests -v"
```

Los tres comparten la misma distribución y trabajan como **root con acceso a todo
su Linux**: pueden editar `/etc`, instalar paquetes y reparar herramientas o servicios.
`--path` selecciona el directorio de trabajo; no limita el acceso root. Los cambios
de este modo se aplican directamente al WSL, incluso si luego falla una prueba o se
interrumpe la sesión. Haz un export si necesitas poder recuperar su estado completo:

```powershell
wsl.exe --export AgentLab-Repair C:\ruta-con-espacio\agentlab-backup.tar
```

Automount de discos Windows, lectura de fstab, interop con ejecutables Windows y
herencia del PATH Windows quedan desactivados. El backend comprueba esos ajustes,
la marca del instalador y que no haya montajes DrvFs ni socket WSL_INTEROP en la sesión antes de
iniciar. Solo admite nombres `AgentLab-*` preparados por el instalador.

**El acceso root completo y el aislamiento frente a código hostil son garantías
distintas.** Root puede cambiar la configuración y WSL comparte infraestructura con
Windows y otras distribuciones. No es una VM independiente ni una frontera fuerte
de seguridad. La red sigue disponible para descargar dependencias. Para código no
confiable que deba quedar fuertemente confinado hace falta una VM separada y su
política de red. Véanse la [configuración oficial de WSL](https://learn.microsoft.com/en-us/windows/wsl/wsl-config),
el [modelo de seguridad](https://wsl.dev/technical-documentation/security/) y los
[comandos de exportación/importación](https://learn.microsoft.com/en-us/windows/wsl/basic-commands).

## Acuerdo, ejecución y resultado

1. Ejecuta las pruebas iniciales y registra sus salidas reales.
2. Un agente propone leer, buscar, reemplazar, escribir, borrar un archivo, ejecutar
   un comando, probar o finalizar.
3. Lecturas y el comando de pruebas configurado pueden ejecutarse directamente.
   Cada edición y cualquier otro comando requieren el voto de los tres. Cada uno
   revisa la propuesta exacta por separado antes de ver los votos de sus compañeros.
4. Un solo `request_changes` impide la ejecución. Su razón vuelve a la discusión compartida
   para que el siguiente proponente la resuelva.
5. Después de cada cambio aprobado ejecuta automáticamente el comando de pruebas.
   Al solicitar cierre, repite las pruebas y solicita aprobación unánime
   del resultado. Las pruebas anteriores a un cambio nunca bastan para cerrarlo.

No se inyectan los prompts narrativos, memorias, secretos ni Vault de los personajes.
Se utilizan los tres endpoints configurados y la adaptación de transporte elegida para cada modelo.
La salida JSON se restringe con gramática GBNF y se valida antes de ejecutar.

Opciones: `--max-steps 36` limita propuestas; `--timeout 120` limita cada comando.
`--config` y `--runs` se pasan **antes** de `folder` o `wsl`. Un límite agotado,
desacuerdo, fallo o Ctrl+C conserva el trabajo y no se anuncia como reparación exitosa.
Las sesiones se conservan para inspección; todavía no hay reanudación automática.
Un bloqueo del sistema operativo impide dos reparaciones sobre el mismo destino.
La carga por turnos también reserva el conjunto local de modelos durante la sesión.

Cada sesión en `%LOCALAPPDATA%\AgentLab\repairs\<fecha-id>` contiene los archivos
indicados abajo. Puedes cambiar esa ubicación con `--runs` antes de `folder`/`wsl`.

- `discussion.jsonl`: propuestas, votos, decisiones y resultados compartidos.
- `commands/*.log`: salida completa de comandos y pruebas.
- `result.json`: estado, verificación, archivos cambiados y publicación.
- `changes.diff`: diff de la copia de carpeta. En WSL se enumeran archivos del
  proyecto cambiados y comandos; no representa un diff completo del sistema Linux.
- `workspace`, `original`, `backups`: copia y recuperación del modo carpeta.

La ventana de contexto es acotada: los agentes pueden releer archivos; el registro
completo queda en disco. El consenso no garantiza que un modelo razone bien ni que
las pruebas cubran todo. El resultado indica exactamente qué comando se verificó.

## Arranque y comprobación

```powershell
python -m unittest discover -s tests -v
python .\agentlab.py --help
```

Si hay otras cargas grandes de GPU/RAM, limita la descarga a GPU:

```powershell
.\start_servers.ps1 -Restart -DarsGpuLayers 24 -RadeGpuLayers 18 -MisoGpuLayers 18
```

El arranque usa KV q8, lotes menores y capas `auto` por defecto para reducir la
presión de memoria. Si Windows tiene menos de 18 GB de memoria virtual disponible,
activa un perfil CPU para los agentes sin capas GPU explícitas. Puedes forzarlo
con `-LowMemory`; las sesiones gestionadas por turnos pueden usar 8 capas GPU si hay
margen suficiente. `-Restart` solo gestiona los servidores de los puertos 8081,
8082 y 8083; no cierra otros modelos o aplicaciones. Si falta memoria, conserva el
mensaje y diagnóstico de cada servidor en `work/serverlogs`.

La integración de herramientas WSL se puede repetir con:

```powershell
$env:AGENTLAB_WSL_INTEGRATION = '1'
python -m unittest discover -s tests -p 'test_repair*.py' -v
```

Esta integración usa archivos de prueba temporales dentro del WSL dedicado y votos
simulados para verificar el backend. Las sesiones reales de modelos se registran
aparte en la carpeta de sesiones.
