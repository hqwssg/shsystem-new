package com.ruoyi.carbon.report.generation;

import java.nio.file.Files;
import java.nio.file.Path;
import com.ruoyi.carbon.report.domain.ReportFile;
import com.ruoyi.carbon.report.mapper.ReportFileMapper;

/**
 * Reads report bytes from MySQL. An older row may still point at a file; the first read copies it in.
 */
public final class ReportFileBytes
{
    private ReportFileBytes()
    {
    }

    public static byte[] read(ReportFile meta, DiskArtifactStore store, ReportFileMapper mapper)
    {
        if (meta == null || meta.getId() == null || mapper == null)
        {
            return null;
        }
        ReportFile storedRow = mapper.selectContentById(meta.getId());
        byte[] stored = storedRow == null ? null : storedRow.getContent();
        if (stored != null && stored.length > 0)
        {
            return stored;
        }
        if (store == null || meta.getObjectKey() == null || meta.getObjectKey().isBlank())
        {
            return null;
        }
        try
        {
            Path path = store.resolve(meta);
            if (!Files.isRegularFile(path))
            {
                return null;
            }
            byte[] bytes = Files.readAllBytes(path);
            if (bytes.length == 0)
            {
                return null;
            }
            try
            {
                ReportFile update = new ReportFile();
                update.setId(meta.getId());
                update.setContent(bytes);
                update.setSha256(SnapshotHasher.sha256(bytes));
                update.setSizeBytes((long) bytes.length);
                mapper.updateContent(update);
            }
            catch (RuntimeException ignored)
            {
            }
            return bytes;
        }
        catch (Exception ex)
        {
            return null;
        }
    }
}
