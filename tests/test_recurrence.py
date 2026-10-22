from datetime import datetime, timedelta, timezone
from unittest import TestCase, mock
from zoneinfo import ZoneInfo

from werkzeug.datastructures import MultiDict
from web.calendar_service import CalendarError
from web.recurrence import expand_recurrence, recurrence_fields, recurrence_preview


class WeeklyRecurrenceTests(TestCase):
    def rule(self, **changes):
        return {'startDate': '2030-01-07', 'endDate': '2030-01-31', 'weekdays': [1, 4], 'startTime': '10:00', **changes}

    def test_multiple_weekdays_are_real_sorted_dated_intervals(self):
        result=expand_recurrence(self.rule(),120,zone=ZoneInfo('Europe/Istanbul'))
        self.assertEqual(len(result['intervals']),8)
        self.assertEqual(result['intervals'][0][0],datetime(2030,1,7,7,tzinfo=timezone.utc))
        self.assertEqual(result['intervals'][-1][0],datetime(2030,1,31,7,tzinfo=timezone.utc))
        self.assertTrue(all(b-a==timedelta(hours=2) for a,b in result['intervals']))

    def test_eight_separate_wednesdays_do_not_collapse_onto_a_weekday(self):
        result=expand_recurrence(self.rule(startDate='2030-01-09',endDate='2030-02-27',weekdays=[3]),60)
        self.assertEqual(len(result['intervals']),8)
        self.assertEqual(len({a.date() for a,b in result['intervals']}),8)

    def test_date_bounds_are_inclusive_and_allow_one_occurrence(self):
        self.assertEqual(len(expand_recurrence(self.rule(endDate='2030-01-07',weekdays=[1]),60)['intervals']),1)

    def test_empty_pattern_is_rejected(self):
        with self.assertRaises(CalendarError):expand_recurrence(self.rule(endDate='2030-01-07',weekdays=[2]),60)

    def test_invalid_types_days_times_and_dates(self):
        for changes in ({'weekdays':[]},{'weekdays':[True]},{'weekdays':[1,1]},{'weekdays':[8]},
                        {'startTime':'24:00'},{'startTime':'10:00:30'},{'startDate':'2030-02-30'},
                        {'endDate':'2029-12-31'},{'startDate':'2030-W02-1'},{'endDate':None}):
            with self.subTest(changes=changes),self.assertRaises(CalendarError):expand_recurrence(self.rule(**changes),60)

    def test_invalid_durations_and_unbounded_ranges(self):
        for duration in (True,0,-1,525601,'60'):
            with self.subTest(duration=duration),self.assertRaises(CalendarError):expand_recurrence(self.rule(),duration)
        with self.assertRaises(CalendarError):expand_recurrence(self.rule(endDate='2033-01-01'),60)

    def test_execution_count_limit_is_explicit(self):
        with self.assertRaisesRegex(CalendarError,'1-366'):expand_recurrence(self.rule(endDate='2031-12-31',weekdays=list(range(1,8))),60)

    def test_overlapping_equipment_periods_rejected_not_silently_merged(self):
        with self.assertRaisesRegex(CalendarError,'overlap'):expand_recurrence(self.rule(weekdays=[1,2]),2*1440)

    def test_adjacent_periods_allowed_and_multiday_returns_previewed(self):
        result=expand_recurrence(self.rule(weekdays=[1,2]),1440)
        self.assertEqual(result['intervals'][0][1],result['intervals'][1][0])
        self.assertEqual(len(recurrence_preview(result)),len(result['intervals']))

    def test_university_timezone_is_explicit_not_host_timezone(self):
        with mock.patch.dict('os.environ',{'RESOURCE_ALLOCATION_TIMEZONE':'Europe/Istanbul'}):
            self.assertEqual(expand_recurrence(self.rule(),60)['timezone'],'Europe/Istanbul')

    def test_dst_gap_and_fold_fail_without_guessing(self):
        for day in ('2030-03-10','2030-11-03'):
            with self.subTest(day=day),self.assertRaises(CalendarError):
                expand_recurrence(self.rule(startDate=day,endDate=day,weekdays=[7],startTime='02:30' if day.endswith('03-10') else '01:30'),30,zone=ZoneInfo('America/New_York'))

    def test_future_validation_is_optional_for_reloading_history(self):
        now=datetime(2030,1,7,10,tzinfo=timezone.utc)
        with self.assertRaises(CalendarError):expand_recurrence(self.rule(),60,now=now)
        self.assertTrue(expand_recurrence(self.rule(),60)['intervals'])

    def test_elapsed_duration_can_cross_a_dst_transition(self):
        zone=ZoneInfo('America/New_York')
        result=expand_recurrence(self.rule(startDate='2030-03-10',endDate='2030-03-10',weekdays=[7],startTime='01:59'),2,zone=zone)
        start,end=result['intervals'][0]
        self.assertEqual(end-start,timedelta(minutes=2))
        self.assertEqual(end.astimezone(zone).strftime('%H:%M'),'03:01')

    def test_browser_mode_and_fields_are_bounded_and_do_not_choose_timezone(self):
        self.assertIsNone(recurrence_fields(MultiDict()))
        form=MultiDict([('reservationMode','weekly'),('recurrenceDays','1'),('recurrenceDays','4'),
            ('recurrenceStart','2030-01-07'),('recurrenceEnd','2030-01-31'),('recurrenceTime','10:00'),('timezone','UTC')])
        self.assertEqual(recurrence_fields(form)['weekdays'],[1,4])
        self.assertNotIn('timezone',recurrence_fields(form))
        with self.assertRaises(CalendarError):recurrence_fields(MultiDict({'reservationMode':'forever'}))
