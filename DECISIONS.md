# Implementation Decisions

1. **Indexes.** I used `ix_employee_department_code` to support employee department queries and `uq_attendance_employee_date` to support attendance lookups and prevent duplicate records for the same employee and date. I also use an attendance index matching the status, date, and employee query pattern. I considered indexing every field but rejected it because unnecessary indexes increase storage and write overhead.

2. **Punch-in race.** If two identical punch-in requests arrive together, both may initially check that no record exists. The unique employee-and-date index ensures MongoDB cannot store both records. One request succeeds; the other receives a duplicate-key error, which the API handles as a conflict response.

3. **Ties.** The leaderboard sorts employees by late minutes. If employees tie at the cutoff, the configured limit may exclude an employee with the same score. A secondary sort key would make the ordering deterministic, while including every tied employee would require different cutoff logic.

4. **Headcount.** The department summary starts with employee records and looks up their attendance data. Therefore, employees with no attendance logs can still contribute to department headcount.

5. **One change for 100x data.** I would benchmark the main aggregation pipelines with production-like data, then optimize the slowest queries and indexes based on execution statistics. I would also consider caching frequently requested analytics if measurements showed it was beneficial.