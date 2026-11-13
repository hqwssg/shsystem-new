package com.ruoyi.carbon.report.generation;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;

public final class SnapshotHasher
{
    private SnapshotHasher()
    {
    }

    public static String sha256(String payload)
    {
        return sha256(String.valueOf(payload).getBytes(StandardCharsets.UTF_8));
    }

    public static String sha256(byte[] payload)
    {
        try
        {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(payload == null ? new byte[0] : payload));
        }
        catch (Exception ex)
        {
            throw new IllegalStateException(ex);
        }
    }
}
