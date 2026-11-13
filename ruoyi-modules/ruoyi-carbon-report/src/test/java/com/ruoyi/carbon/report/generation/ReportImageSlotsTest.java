package com.ruoyi.carbon.report.generation;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import com.ruoyi.carbon.report.domain.ReportFile;

class ReportImageSlotsTest
{
    @TempDir
    Path temp;

    @Test
    void snapshotImagesOmitSlotsWithoutStoredFiles()
    {
        assertEquals(0, ReportImageSlots.snapshotImages(null).size());
    }

    @Test
    void snapshotImagesUseDefaultRowWhenUploadIsAbsent()
    {
        ReportFile cover = new ReportFile();
        cover.setId(4L);
        cover.setRole("cover_logo");
        cover.setMimeType("image/png");
        List<?> images = ReportImageSlots.snapshotImages(null, List.of(cover));
        assertEquals(1, images.size());
        JSONObject item = JSON.parseObject(JSON.toJSONString(images.get(0)));
        assertEquals("carbon-file:4", item.getString("url"));
        assertEquals("image/png", item.getString("mime_type"));
    }

    @Test
    void materializeCopiesCarbonFileIntoJobAssets() throws Exception
    {
        Path source = temp.resolve("custom.png");
        Files.write(source, "png-bytes".getBytes(StandardCharsets.UTF_8));
        Path jobAssets = temp.resolve("job-assets");
        String snapshot = "{\"images\":[{\"role\":\"cover_logo\",\"caption\":\"x\","
                + "\"url\":\"carbon-file:12\",\"mime_type\":\"image/png\"},"
                + "{\"role\":\"org_chart\",\"url\":\"/assets/suning/org_chart.png\"}]}";
        String prepared = ReportImageSlots.materialize(snapshot, jobAssets, fileId -> Long.valueOf(12L).equals(fileId) ? source : null);
        JSONObject item = JSON.parseObject(prepared).getJSONArray("images").getJSONObject(0);
        assertEquals("/job-assets/cover_logo.png", item.getString("url"));
        assertTrue(Files.isRegularFile(jobAssets.resolve("cover_logo.png")));
        assertEquals("png-bytes", Files.readString(jobAssets.resolve("cover_logo.png")));
        assertEquals("/assets/suning/org_chart.png",
                JSON.parseObject(prepared).getJSONArray("images").getJSONObject(1).getString("url"));
        assertFalse(prepared.contains("carbon-file:"));
    }

    @Test
    void snapshotImagesPreferUploadId()
    {
        ReportFile file = new ReportFile();
        file.setId(7L);
        file.setRole("office_location");
        file.setMimeType("image/jpeg");
        JSONObject office = JSON.parseObject(JSON.toJSONString(ReportImageSlots.snapshotImages(List.of(file)).get(0)));
        assertEquals("carbon-file:7", office.getString("url"));
        assertEquals("image/jpeg", office.getString("mime_type"));
    }
}
