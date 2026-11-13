package com.ruoyi.carbon.report.service.impl;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import com.ruoyi.carbon.report.domain.ReportDeptProfile;
import com.ruoyi.carbon.report.generation.ActivityProseSanitizer;
import com.ruoyi.carbon.report.mapper.ReportDeptProfileMapper;
import com.ruoyi.carbon.report.service.IReportDeptProfileService;
import com.ruoyi.carbon.report.service.ReportAccessGuard;

@Service
public class ReportDeptProfileServiceImpl implements IReportDeptProfileService
{
    @Autowired
    private ReportDeptProfileMapper profileMapper;

    @Override
    public ReportDeptProfile get(Long deptId)
    {
        return profileMapper.selectByDeptId(deptId);
    }

    @Override
    public ReportDeptProfile save(ReportDeptProfile profile, Long deptId, String username)
    {
        ReportAccessGuard.requireDept(profile.getDeptId() == null ? deptId : profile.getDeptId(), deptId);
        profile.setDeptId(deptId);
        profile.setUpdateBy(username);
        if (profileMapper.selectByDeptId(deptId) == null)
        {
            profile.setCreateBy(username);
            profileMapper.insert(profile);
        }
        else
        {
            profileMapper.update(profile);
        }
        return profileMapper.selectByDeptId(deptId);
    }

    @Override
    public ReportDeptProfile saveActivityProse(Long deptId, String proseJson, String username)
    {
        ReportAccessGuard.requireDept(deptId, deptId);
        String sanitized = ActivityProseSanitizer.sanitize(proseJson).toJSONString();
        ReportDeptProfile existing = profileMapper.selectByDeptId(deptId);
        if (existing == null)
        {
            ReportDeptProfile profile = new ReportDeptProfile();
            profile.setDeptId(deptId);
            profile.setDefaultActivityProseJson(sanitized);
            profile.setCreateBy(username);
            profile.setUpdateBy(username);
            profileMapper.insert(profile);
        }
        else
        {
            profileMapper.updateActivityProse(deptId, sanitized, username);
        }
        return profileMapper.selectByDeptId(deptId);
    }
}
