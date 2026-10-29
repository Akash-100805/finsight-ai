"""`python dev.py run-all`: two supervised loop processes (restart on crash with backoff, Ctrl+C stops both)."""
import os
import sys


repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
import dev  # noqa: E402


class FakeProc:
    created = []

    def __init__(self, argv, cwd=None, env=None):
        self.argv, self.cwd, self.pid = argv, cwd, 1000 + len(FakeProc.created)
        self.polls, self.terminated, self.killed = 0, False, False
        FakeProc.created.append(self)

    def poll(self):
        if self.terminated:
            return -15
        outcome = self.plan.pop(0) if self.plan else None
        return outcome

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


def make_popen(plans):
    """plans: {'news': [[None, 1], [None, None, 0]], ...} one list of poll results per launch, in order."""
    FakeProc.created = []
    launches = {"news": 0, "tkg": 0}

    def popen(argv, cwd=None, env=None):
        name = "tkg" if "tkg_dev.py" in " ".join(argv) else "news"
        proc = FakeProc(argv, cwd, env)
        proc.name = name
        proc.plan = list(plans[name][launches[name]])
        launches[name] += 1
        return proc

    return popen


def test_loop_specs_start_the_news_loop_and_the_tkg_loop():
    specs = dev._loop_specs("main", 30)
    names = [n for n, _, _ in specs]
    assert names == ["news", "tkg"]
    news_argv, tkg_argv = specs[0][1], specs[1][1]
    assert "src.news.pipeline.run_loop" in news_argv and "--interval" in news_argv
    assert tkg_argv[1].endswith("tkg_dev.py") and tkg_argv[2] == "run-loop"
    assert tkg_argv[tkg_argv.index("--initial-delay-minutes") + 1] == "2"        # 2 min after the news loop's schedule


def test_a_crashing_child_is_restarted_with_backoff_and_a_clean_exit_is_not():
    logs, now = [], {"t": 0.0}
    plans = {"news": [[None, 1], [None, 0]],          # crashes once, then exits cleanly
             "tkg": [[None, None, None, None, None, 0]]}   # runs a while, exits cleanly
    popen = make_popen(plans)

    def sleep(seconds):
        now["t"] += seconds

    dev.supervise(dev._loop_specs("test", 30), env={}, poll_seconds=5, backoff_start=15, clock=lambda: now["t"], sleep=sleep,
                  popen=popen, log=logs.append)
    news_launches = [p for p in FakeProc.created if p.name == "news"]
    assert len(news_launches) == 2 and len([p for p in FakeProc.created if p.name == "tkg"]) == 1
    assert any("news exited with code 1; restarting in 15s" in line for line in logs)
    assert any("tkg stopped cleanly" in line for line in logs) and any("news stopped cleanly" in line for line in logs)


def test_ctrl_c_terminates_both_children():
    logs = []
    popen = make_popen({"news": [[None] * 50], "tkg": [[None] * 50]})
    calls = {"n": 0}

    def sleep(seconds):
        calls["n"] += 1
        if calls["n"] > 3:
            raise KeyboardInterrupt

    dev.supervise(dev._loop_specs("test", 30), env={}, clock=lambda: 0.0, sleep=sleep, popen=popen, log=logs.append)
    assert len(FakeProc.created) == 2 and all(p.terminated for p in FakeProc.created)
    assert any("Ctrl+C" in line for line in logs)


def test_backoff_grows_and_is_capped():
    logs, now = [], {"t": 0.0}
    popen = make_popen({"news": [[1], [1], [1], [1], [0]], "tkg": [[0]]})

    def sleep(seconds):
        now["t"] += seconds

    dev.supervise(dev._loop_specs("test", 30), env={}, poll_seconds=1, backoff_start=15, backoff_max=40, stable_after=10_000,
                  clock=lambda: now["t"], sleep=sleep, popen=popen, log=logs.append)
    waits = [int(line.split("restarting in ")[1].split("s")[0]) for line in logs if "restarting in" in line]
    assert waits == [15, 30, 40, 40]
