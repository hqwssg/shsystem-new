package com.ruoyi.carbon.report.service;

import java.net.URI;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import com.ruoyi.carbon.report.generation.LlmRuntimeConfig;
import com.ruoyi.carbon.report.mapper.ReportLlmConfigMapper;
import com.ruoyi.common.core.constant.HttpStatus;
import com.ruoyi.common.core.exception.ServiceException;

@Service
public class ReportLlmConfigService
{
    private static final String BASE_URL_KEY = "carbon.report.llm.default.baseUrl";
    private static final String MODEL_KEY = "carbon.report.llm.default.model";
    private static final String API_KEY_KEY = "carbon.report.llm.default.apiKeyEncrypted";
    private static final String DEFAULT_BASE_URL = "https://api.deepseek.com";
    private static final String DEFAULT_MODEL = "deepseek-reasoner";
    private final ReportLlmConfigMapper mapper;
    private final Environment environment;
    private final SecureRandom random = new SecureRandom();

    public ReportLlmConfigService(ReportLlmConfigMapper mapper, Environment environment)
    {
        this.mapper = mapper;
        this.environment = environment;
    }

    public Map<String, Object> publicSettings(boolean admin)
    {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("baseUrl", value(BASE_URL_KEY, env("CARBON_REPORT_LLM_BASE_URL", DEFAULT_BASE_URL)));
        result.put("model", value(MODEL_KEY, env("CARBON_REPORT_LLM_MODEL", DEFAULT_MODEL)));
        result.put("apiKey", defaultApiKey());
        result.put("apiKeyConfigured", hasDefaultApiKey());
        result.put("isAdmin", admin);
        return result;
    }

    public LlmRuntimeConfig resolve(Map<String, Object> request)
    {
        String baseUrl = request == null ? null : string(request.get("baseUrl"));
        String model = request == null ? null : string(request.get("model"));
        String apiKey = request == null ? null : string(request.get("apiKey"));
        baseUrl = validateBaseUrl(blank(baseUrl) ? value(BASE_URL_KEY, env("CARBON_REPORT_LLM_BASE_URL", DEFAULT_BASE_URL)) : baseUrl);
        model = validateModel(blank(model) ? value(MODEL_KEY, env("CARBON_REPORT_LLM_MODEL", DEFAULT_MODEL)) : model);
        if (blank(apiKey)) apiKey = defaultApiKey();
        return new LlmRuntimeConfig(baseUrl, model, apiKey);
    }

    @Transactional(rollbackFor = Exception.class)
    public void saveDefault(Map<String, Object> request, String username)
    {
        if (request == null) throw new ServiceException("请填写默认 AI 配置", HttpStatus.BAD_REQUEST);
        String baseUrl = validateBaseUrl(string(request.get("baseUrl")));
        String model = validateModel(string(request.get("model")));
        String apiKey = string(request.get("apiKey"));
        if (!blank(apiKey) && apiKey.getBytes(StandardCharsets.UTF_8).length > 300)
            throw new ServiceException("API Key 过长，不能设置为全局默认值", HttpStatus.BAD_REQUEST);
        if (blank(apiKey))
        {
            String currentEncrypted = mapper.selectValue(API_KEY_KEY);
            if (currentEncrypted != null && !currentEncrypted.isBlank()) decrypt(currentEncrypted);
        }
        saveValue("报告 AI 默认服务地址", BASE_URL_KEY, baseUrl, username, "碳排放报告 AI 全局默认配置");
        saveValue("报告 AI 默认模型", MODEL_KEY, model, username, "碳排放报告 AI 全局默认配置");
        if (!blank(apiKey)) saveValue("报告 AI 默认密钥（加密）", API_KEY_KEY, encrypt(apiKey), username, "AES-GCM 加密存储");
    }

    private String defaultApiKey()
    {
        String encrypted = mapper.selectValue(API_KEY_KEY);
        if (encrypted != null && !encrypted.isBlank()) return decrypt(encrypted);
        String configured = env("CARBON_REPORT_LLM_API_KEY", env("OPENAI_API_KEY", ""));
        return blank(configured) ? null : configured;
    }

    private boolean hasDefaultApiKey()
    {
        String encrypted = mapper.selectValue(API_KEY_KEY);
        return (encrypted != null && !encrypted.isBlank())
                || !blank(env("CARBON_REPORT_LLM_API_KEY", env("OPENAI_API_KEY", "")));
    }

    private void saveValue(String name, String key, String value, String username, String remark)
    {
        if (mapper.updateValue(key, value, username) == 0)
            mapper.insertValue(name, key, value, username, remark);
    }

    private String encrypt(String plain)
    {
        try
        {
            byte[] iv = new byte[12];
            random.nextBytes(iv);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, encryptionKey(), new GCMParameterSpec(128, iv));
            byte[] encrypted = cipher.doFinal(plain.getBytes(StandardCharsets.UTF_8));
            return "v1:" + Base64.getEncoder().encodeToString(ByteBuffer.allocate(iv.length + encrypted.length).put(iv).put(encrypted).array());
        }
        catch (Exception ex)
        {
            throw new ServiceException("无法加密默认 API Key，请检查服务端 CARBON_REPORT_LLM_CONFIG_ENCRYPTION_KEY 配置");
        }
    }

    private String decrypt(String value)
    {
        try
        {
            if (!value.startsWith("v1:")) throw new IllegalArgumentException("unsupported key format");
            ByteBuffer buffer = ByteBuffer.wrap(Base64.getDecoder().decode(value.substring(3)));
            byte[] iv = new byte[12];
            buffer.get(iv);
            byte[] encrypted = new byte[buffer.remaining()];
            buffer.get(encrypted);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, encryptionKey(), new GCMParameterSpec(128, iv));
            return new String(cipher.doFinal(encrypted), StandardCharsets.UTF_8);
        }
        catch (Exception ex)
        {
            throw new ServiceException("默认 API Key 无法解密，请检查服务端 CARBON_REPORT_LLM_CONFIG_ENCRYPTION_KEY 配置");
        }
    }

    private SecretKeySpec encryptionKey() throws Exception
    {
        String secret = env("CARBON_REPORT_LLM_CONFIG_ENCRYPTION_KEY", "");
        if (blank(secret)) throw new IllegalStateException("encryption key is not configured");
        return new SecretKeySpec(MessageDigest.getInstance("SHA-256").digest(secret.getBytes(StandardCharsets.UTF_8)), "AES");
    }

    private String validateBaseUrl(String value)
    {
        if (blank(value) || value.length() > 500) throw new ServiceException("AI 服务地址不能为空，且不能超过 500 个字符", HttpStatus.BAD_REQUEST);
        try
        {
            URI uri = URI.create(value.trim());
            if (!("http".equalsIgnoreCase(uri.getScheme()) || "https".equalsIgnoreCase(uri.getScheme()))
                    || uri.getHost() == null || uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null)
                throw new IllegalArgumentException("invalid URI");
            return value.trim().replaceAll("/+$", "");
        }
        catch (Exception ex)
        {
            throw new ServiceException("AI 服务地址必须是有效的 HTTP 或 HTTPS 地址", HttpStatus.BAD_REQUEST);
        }
    }

    private String validateModel(String value)
    {
        if (blank(value) || value.length() > 200) throw new ServiceException("模型名称不能为空，且不能超过 200 个字符", HttpStatus.BAD_REQUEST);
        return value.trim();
    }

    private String value(String key, String fallback)
    {
        String configured = mapper.selectValue(key);
        return blank(configured) ? fallback : configured;
    }

    private String env(String key, String fallback)
    {
        String configured = environment.getProperty(key);
        return blank(configured) ? fallback : configured;
    }

    private static String string(Object value) { return value == null ? "" : String.valueOf(value).trim(); }
    private static boolean blank(String value) { return value == null || value.isBlank(); }
}
