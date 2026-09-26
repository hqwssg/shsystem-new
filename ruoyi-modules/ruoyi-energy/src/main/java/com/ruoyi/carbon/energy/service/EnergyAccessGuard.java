package com.ruoyi.carbon.energy.service;

import com.ruoyi.common.core.constant.HttpStatus;
import com.ruoyi.common.core.exception.ServiceException;

public final class EnergyAccessGuard
{
    public static final String[] RUN_TYPES = {
        "timetable_audit",
        "timetable_optimization",
        "dispatch",
        "rolling_rescheduling",
        "joint_parameter_robustness"
    };

    private EnergyAccessGuard()
    {
    }

    public static void requireDept(Long requestedDeptId, Long allowedDeptId)
    {
        if (requestedDeptId == null || allowedDeptId == null || !requestedDeptId.equals(allowedDeptId))
        {
            throw new ServiceException("not found", HttpStatus.NOT_FOUND);
        }
    }

    public static void requireBound(boolean bound)
    {
        if (!bound)
        {
            throw new ServiceException("当前部门未绑定该能量项目", HttpStatus.NOT_FOUND);
        }
    }

    public static String requireRunType(String runType)
    {
        if (runType == null)
        {
            throw new ServiceException("run_type 不能为空", HttpStatus.BAD_REQUEST);
        }
        for (String allowed : RUN_TYPES)
        {
            if (allowed.equals(runType))
            {
                return runType;
            }
        }
        throw new ServiceException("不支持的任务类型: " + runType, HttpStatus.BAD_REQUEST);
    }

    public static void requireRelativePath(String relativePath)
    {
        if (relativePath == null || relativePath.isBlank())
        {
            throw new ServiceException("relative_path 不能为空", HttpStatus.BAD_REQUEST);
        }
        String normalized = relativePath.replace('\\', '/');
        if (normalized.startsWith("/") || normalized.contains(".."))
        {
            throw new ServiceException("非法文件路径", HttpStatus.BAD_REQUEST);
        }
    }

    public static String relativePath(String relativePath)
    {
        requireRelativePath(relativePath);
        return relativePath.replace('\\', '/').trim();
    }
}
