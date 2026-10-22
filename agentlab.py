"""AgentLab Consensus: collaborative code and dedicated WSL repair."""
import sys

if sys.version_info < (3, 11):
    raise SystemExit('AgentLab necesita Python 3.11 o posterior. Instálalo desde python.org y vuelve a iniciar el asistente.')

from repair import main

if __name__ == "__main__":
    raise SystemExit(main())
