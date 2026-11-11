from pathlib import Path
source = Path('tests/workspace/stage-states.test.ts').read_text()
code = source.split('/* MUTATION_RUNNER_PYTHON\n', 1)[1].split('MUTATION_RUNNER_PYTHON */', 1)[0]
exec(compile(code, 'stage-mutation-runner', 'exec'))
