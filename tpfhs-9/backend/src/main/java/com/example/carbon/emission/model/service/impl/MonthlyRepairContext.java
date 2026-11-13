package com.example.carbon.emission.model.service.impl;

import java.time.YearMonth;
import java.util.Set;

record MonthlyRepairContext(YearMonth month, boolean pastDeadline, Set<Point> waitingPoints, long revision) {
    MonthlyRepairContext {
        waitingPoints = Set.copyOf(waitingPoints);
    }

    record Point(int type, long id) {}
}
