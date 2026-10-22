"""When the paid odds refresh runs.

It used to be Thursday and Monday, then Thursday and Sunday. Monday came after
everything had been played; Sunday priced the main slate a few hours before
kickoff but overlapped Thursday, which bought the same thirteen games twice and
put the month over its 500-credit quota.

Now Thursday and Saturday, with windows that meet rather than overlap: Thursday
takes Thursday night and Friday, Saturday takes its own fixtures through Monday
night. Saturday is also a day earlier than Sunday was, which leaves time to act
on a line and time to notice a failed run.

The hour is local rather than UTC so it stays at the same time of morning either
side of the October clock change. The scheduler and /odds/status read the same
spec deliberately, so these tests check they cannot disagree.
"""

import datetime
import sys

import pytest

nfl_helper = sys.modules["nfl_helper"]

import odds_api as oa

from apscheduler.triggers.cron import CronTrigger

UTC = datetime.timezone.utc


def the_trigger():
    return CronTrigger(
        day_of_week=",".join(oa.REFRESH_CRON_DAYS),
        hour=oa.REFRESH_HOUR_LOCAL,
        minute=0,
        timezone=oa.REFRESH_TIMEZONE,
    )


def fire_times(count, start):
    trigger, out, cursor = the_trigger(), [], start
    for _ in range(count):
        cursor = trigger.get_next_fire_time(None, cursor)
        out.append(cursor)
        cursor = cursor + datetime.timedelta(seconds=1)
    return out


class TestTheDays:
    def test_it_runs_thursday_and_saturday(self):
        assert set(oa.REFRESH_CRON_DAYS) == {"thu", "sat"}

    def test_the_days_it_has_outgrown_are_not_in_there(self):
        assert "mon" not in oa.REFRESH_CRON_DAYS
        assert "sun" not in oa.REFRESH_CRON_DAYS

    def test_the_weekday_numbers_match_the_cron_names(self):
        """Two spellings of the same thing: the cron drives the scheduler and
        the numbers drive /odds/status, and they have to agree."""
        by_name = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
        assert set(oa.REFRESH_WEEKDAYS) == {by_name[d] for d in oa.REFRESH_CRON_DAYS}

    def test_the_schedule_actually_fires_on_those_days(self):
        days = {t.strftime("%a").lower() for t in fire_times(6, datetime.datetime(2026, 10, 4, 6, 0, tzinfo=UTC))}
        assert days == {"thu", "sat"}


class TestTheHourSurvivesTheClockChange:
    def test_summer_time_fires_at_08_00_utc(self):
        """10:00 CEST."""
        run = fire_times(1, datetime.datetime(2026, 10, 4, 6, 0, tzinfo=UTC))[0]
        assert run.astimezone(UTC).hour == 8
        assert run.hour == oa.REFRESH_HOUR_LOCAL

    def test_winter_time_fires_at_09_00_utc(self):
        """10:00 CET — the hour of the morning is what is held fixed, which is
        the whole point of scheduling in a named zone rather than in UTC."""
        run = fire_times(1, datetime.datetime(2026, 11, 10, 6, 0, tzinfo=UTC))[0]
        assert run.astimezone(UTC).hour == 9
        assert run.hour == oa.REFRESH_HOUR_LOCAL

    def test_the_local_hour_is_the_same_either_side(self):
        before = fire_times(1, datetime.datetime(2026, 10, 20, 6, 0, tzinfo=UTC))[0]
        after = fire_times(1, datetime.datetime(2026, 11, 3, 6, 0, tzinfo=UTC))[0]
        assert before.hour == after.hour == 10
        assert before.astimezone(UTC).hour != after.astimezone(UTC).hour


class TestTheJobThatIsActuallyRegistered:
    """Reading the real registration, not a reconstruction of it.

    Rebuilding the trigger from the constants proves the constants are right and
    nothing else: dropping `timezone=` from the cron in nfl-helper.py left every
    other test in this file green while silently moving the run an hour every
    winter. These read the job the scheduler was actually given.
    """

    def the_registered_trigger(self):
        found = [c.kwargs["trigger"] for c in nfl_helper.scheduler.add_job.call_args_list
                 if c.kwargs["func"].__name__ == "_refresh_odds"]
        assert len(found) == 1, f"expected one odds refresh job, found {len(found)}"
        return found[0]

    def test_it_is_registered_for_thursday_and_saturday(self):
        assert "day_of_week='thu,sat'" in str(self.the_registered_trigger())

    def test_it_is_registered_in_a_named_zone_not_utc(self):
        trigger = self.the_registered_trigger()
        assert str(getattr(trigger, "timezone", "")) == oa.REFRESH_TIMEZONE_NAME, (
            "the cron must carry the timezone, or the hour drifts with the clocks"
        )

    def test_the_registered_job_fires_when_status_says_it_will(self):
        """The end-to-end version: the job the scheduler holds and the figure
        /odds/status prints have to be the same moment."""
        when = datetime.datetime(2026, 11, 10, 12, 0)
        _prev, reported = oa._scheduled_runs_around(when)
        actual = self.the_registered_trigger().get_next_fire_time(
            None, when.replace(tzinfo=UTC)).astimezone(UTC).replace(tzinfo=None)
        assert reported == actual


class TestStatusAgreesWithTheScheduler:
    """/odds/status computes next/overdue itself. If it drifts from the cron it
    reports a refresh that never happens, or calls a healthy one overdue."""

    @pytest.mark.parametrize("when", [
        datetime.datetime(2026, 10, 4, 6, 0),    # Sunday, before the run
        datetime.datetime(2026, 10, 6, 12, 0),   # Tuesday, between runs
        datetime.datetime(2026, 11, 10, 12, 0),  # after the clock change
    ])
    def test_the_next_run_it_reports_is_one_the_cron_fires(self, when):
        _prev, nxt = oa._scheduled_runs_around(when)
        from_cron = the_trigger().get_next_fire_time(
            None, when.replace(tzinfo=UTC)).astimezone(UTC).replace(tzinfo=None)
        assert nxt == from_cron

    def test_the_previous_run_is_before_now_and_the_next_after(self):
        now = datetime.datetime(2026, 10, 6, 12, 0)
        prev, nxt = oa._scheduled_runs_around(now)
        assert prev < now < nxt

    def test_it_reports_winter_runs_an_hour_later_in_utc(self):
        _p, summer = oa._scheduled_runs_around(datetime.datetime(2026, 10, 20, 12, 0))
        _p, winter = oa._scheduled_runs_around(datetime.datetime(2026, 11, 3, 12, 0))
        assert summer.hour == 8 and winter.hour == 9


class TestTheStartupBudgetStillHolds:
    def test_the_max_age_covers_the_widest_gap(self):
        """STARTUP_REFRESH_MAX_AGE_HOURS exists so a restart only spends credits
        when a scheduled run was genuinely missed. Narrowing the gaps without
        checking this would make every boot after a long weekend pay."""
        runs = fire_times(8, datetime.datetime(2026, 10, 4, 6, 0, tzinfo=UTC))
        gaps = [(b - a).total_seconds() / 3600 for a, b in zip(runs, runs[1:])]
        assert max(gaps) <= oa.STARTUP_REFRESH_MAX_AGE_HOURS
        assert max(gaps) == pytest.approx(120, abs=1), "Sat -> Thu is five days"
        assert min(gaps) == pytest.approx(48, abs=1), "Thu -> Sat is two"

    def test_the_budget_was_widened_with_the_days(self):
        """The gap grew from four days to five when Sunday became Saturday. Left
        at 96 hours, a restart on the Tuesday or Wednesday would read as a
        missed run and buy a refresh it did not need."""
        assert oa.STARTUP_REFRESH_MAX_AGE_HOURS == 120
