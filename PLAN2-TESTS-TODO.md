> DONE (Phase B): all listed tests re-homed into kento-cli/tests/ (test_cli.py,
> test_input_validators.py, test_cli_*.py) + conftest.py autouse fixtures.

# CLI tests to re-home into kento-cli (removed from kento-core in Task 5)
# Content preserved in kento-core git history (see SHA) + kento-archived repo.

Source SHA in kento-core before removal: f235567

## Whole-file removals (git rm)

- tests/test_cli.py  (whole file — argparse surface, dispatch, routing, parse_network)
- tests/test_input_validators.py  (whole file — _validate_port, _validate_memory, _validate_cores, _validate_ip, bridge existence, CLI-level rejection, F18 vm port auto)

## Embedded-class extractions (class removed from otherwise-library test file)

- tests/test_validate_name.py :: class TestCLIIntegration
  (CLI entry points reject bad names; tests cli.main(["lxc","create",...]) and
  cli.main(["start",...]), cli.main(["info",...]))

- tests/test_attach.py :: class TestCliRouting
  (bare attach/enter, lxc attach, vm attach/enter routing; propagates nonzero exit)

- tests/test_exec.py :: class TestCliRouting
  (bare exec with/without --, lxc exec, vm exec, flags after --, propagates nonzero exit)

- tests/test_logs.py :: class TestCliRouting
  (bare logs, logs with -f/-n flags, lxc logs, vm logs, propagates nonzero exit)

- tests/test_info.py :: class TestCliInfo
  (info/inspect in --help, info --help, inspect --help, lxc/vm info/inspect --help,
  info requires name, info in lxc/vm --help)

- tests/test_create_passthrough.py :: class TestQemuArgCli
  (--qemu-arg in vm create --help, passes through on vm, default None, rejected on lxc)

- tests/test_create_passthrough.py :: class TestLxcArgCli
  (--lxc-arg in lxc create --help, passes through on plain lxc, default None,
  rejected on vm scope, rejected on pve host, rejected on explicit --pve)

- tests/test_create_passthrough.py :: class TestPveArgCli
  (--pve-arg in lxc/vm create --help, passes through on pve-lxc and pve-vm,
  rejected on plain lxc/vm, rejected on explicit --no-pve)

## Notes

- The storage/persistence classes in test_create_passthrough.py
  (TestQemuArgStorage, TestLxcArgStorage, TestPveArgStorage) were kept in
  kento-core as they test kento.create.create() directly, not kento.cli.main().
- To retrieve any removed test verbatim: git show f235567:tests/<file>.py
  in the kento-core repo, or consult the kento-archived repo.
