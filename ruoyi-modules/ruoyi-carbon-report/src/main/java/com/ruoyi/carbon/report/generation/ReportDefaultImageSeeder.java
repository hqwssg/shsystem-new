package com.ruoyi.carbon.report.generation;

import java.nio.file.Files;
import java.nio.file.Path;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;
import com.ruoyi.carbon.report.domain.ReportFile;
import com.ruoyi.carbon.report.mapper.ReportDeptProfileMapper;
import com.ruoyi.carbon.report.mapper.ReportFileMapper;

/**
 * Copies the 肃宁 default images into report_file once, when the renderer directory still has them.
 */
@Component
@ConditionalOnProperty(name = "carbon.report.defaults.seed-legacy-suning-images", havingValue = "true")
public class ReportDefaultImageSeeder implements ApplicationRunner
{
    private final CarbonReportRendererProperties properties;
    private final ReportDeptProfileMapper profileMapper;
    private final ReportFileMapper fileMapper;

    public ReportDefaultImageSeeder(CarbonReportRendererProperties properties,
            ReportDeptProfileMapper profileMapper, ReportFileMapper fileMapper)
    {
        this.properties = properties;
        this.profileMapper = profileMapper;
        this.fileMapper = fileMapper;
    }

    @Override
    public void run(ApplicationArguments args)
    {
        try
        {
            Long deptId = profileMapper.selectDeptIdByEntityCode("suning");
            if (deptId == null)
            {
                return;
            }
            for (ReportImageSlots.Slot slot : ReportImageSlots.slots())
            {
                if (fileMapper.selectDefault(deptId, slot.role) != null)
                {
                    continue;
                }
                Path path = ReportImageSlots.defaultAssetPath(properties.moduleRootPath(), slot.role);
                if (!Files.isRegularFile(path))
                {
                    continue;
                }
                byte[] bytes = Files.readAllBytes(path);
                if (bytes.length == 0)
                {
                    continue;
                }
                ReportFile file = new ReportFile();
                file.setDeptId(deptId);
                file.setKind("default");
                file.setRole(slot.role);
                file.setObjectKey("");
                file.setContent(bytes);
                file.setOriginalName(slot.filename);
                file.setMimeType(slot.mimeType);
                file.setSizeBytes((long) bytes.length);
                file.setSha256(SnapshotHasher.sha256(bytes));
                file.setSnapshotSha256("");
                file.setCreateBy("system");
                file.setUpdateBy("system");
                fileMapper.insert(file);
            }
        }
        catch (Exception ex)
        {
            // The column may not exist yet, or the source files are absent. Leave the page unconfigured.
        }
    }
}
