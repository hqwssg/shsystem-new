package com.ruoyi.common.core.utils;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Path;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import com.ruoyi.common.core.exception.ServiceException;

/** HTTP transport for the named Python jobs hosted by the Python container. */
public final class PythonServiceClient
{
    private static final HttpClient HTTP = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(5)).build();

    private PythonServiceClient() { }

    private static String setting(String name)
    {
        return System.getProperty(name, System.getenv().getOrDefault(name, ""));
    }

    public static boolean enabled()
    {
        return !setting("PYTHON_SERVICE_URL").isBlank();
    }

    /** A production app must not silently start a local Python process. */
    public static boolean required()
    {
        return Boolean.parseBoolean(setting("PYTHON_SERVICE_REQUIRED"));
    }

    public static void requireConfigured()
    {
        if (!enabled() && required())
            throw new ServiceException("PYTHON_SERVICE_URL is required when PYTHON_SERVICE_REQUIRED=true");
    }

    public static JSONObject capabilities()
    {
        return request("/v1/capabilities", null, 10);
    }

    public static JSONObject run(List<String> command, Path cwd, Map<String, String> env,
            Duration timeout, int maxOutputBytes)
    {
        if (command.size() < 2)
            throw new ServiceException("Invalid Python service command");
        String module = command.size() > 2 && "-m".equals(command.get(1)) ? command.get(2) : "";
        String task = switch (module)
        {
            case "carbon_report_agent.cli" -> "report";
            case "carbon_report_agent.markdown_export" -> "markdown";
            case "database.cli" -> "energy";
            case "single_train_recovery_agent.cli" -> "single-train";
            default -> command.get(1).replace('\\', '/').endsWith("/steam_calculator.py")
                    || "steam_calculator.py".equals(command.get(1)) ? "steam" : null;
        };
        if (task == null)
            throw new ServiceException("Unsupported Python business module");

        Map<String, String> forwarded = new LinkedHashMap<>();
        if (env != null)
        {
            for (String key : List.of("CARBON_REPORT_JOB_ASSETS_DIR", "MPLCONFIGDIR",
                    "CARBON_REPORT_LLM_BASE_URL", "CARBON_REPORT_LLM_MODEL",
                    "CARBON_REPORT_LLM_API_KEY", "OPENAI_API_KEY", "SINGLE_TRAIN_RESULT_ROOT",
                    "SINGLE_TRAIN_SOLVE_TIMEOUT"))
            {
                if (env.containsKey(key))
                    forwarded.put(key, env.get(key));
            }
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("task", task);
        payload.put("args", command.subList("steam".equals(task) ? 2 : 3, command.size()));
        if ("report".equals(task))
            payload.put("cwd", cwd.toAbsolutePath().toString());
        payload.put("env", forwarded);
        int seconds = (int) Math.max(1, Math.min(7500, timeout.toSeconds()));
        payload.put("timeoutSeconds", seconds);
        payload.put("maxOutputBytes", Math.max(1024, Math.min(16777216, maxOutputBytes)));
        // Identical later requests are distinct submissions and must not reuse an old task.
        payload.put("idempotencyKey", task + ":" + UUID.randomUUID());

        JSONObject accepted = request("/v1/tasks", payload, 15);
        String taskId = accepted.getString("taskId");
        if (taskId == null || taskId.isBlank())
            throw new ServiceException("Python service did not return a task id");

        long deadline = System.nanoTime() + Duration.ofSeconds(seconds + 30L).toNanos();
        while (System.nanoTime() < deadline)
        {
            JSONObject state = request("/v1/tasks/" + taskId, null, 15);
            String status = state.getString("status");
            if ("succeeded".equals(status) || "failed".equals(status) || "cancelled".equals(status))
            {
                if ("cancelled".equals(status))
                    throw new ServiceException("Python task finished with status: " + status);
                JSONObject result = state.getJSONObject("result");
                if (result == null)
                    throw new ServiceException("Python service did not return a task result");
                if (result.getBooleanValue("timedOut"))
                    throw new ServiceException("Python task timed out");
                return result;
            }
            try
            {
                Thread.sleep(500L);
            }
            catch (InterruptedException ex)
            {
                Thread.currentThread().interrupt();
                throw new ServiceException("Python task polling was interrupted");
            }
        }
        throw new ServiceException("Python task polling timed out; task id: " + taskId);
    }

    private static JSONObject request(String path, Object payload, int timeout)
    {
        String token = setting("PYTHON_INTERNAL_TOKEN");
        if (token.length() < 32)
            throw new ServiceException("Python internal token is not configured");
        try
        {
            String base = setting("PYTHON_SERVICE_URL").replaceAll("/+$", "");
            HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(base + path))
                    .timeout(Duration.ofSeconds(timeout))
                    .header("Authorization", "Bearer " + token);
            if (payload == null)
                builder.GET();
            else
                builder.header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(JSON.toJSONString(payload)));
            HttpResponse<String> response = HTTP.send(builder.build(), HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() != 200 && response.statusCode() != 202)
                throw new ServiceException("Python service request failed: HTTP " + response.statusCode());
            return JSON.parseObject(response.body());
        }
        catch (ServiceException ex)
        {
            throw ex;
        }
        catch (InterruptedException ex)
        {
            Thread.currentThread().interrupt();
            throw new ServiceException("Python service request was interrupted");
        }
        catch (Exception ex)
        {
            throw new ServiceException("Python service connection failed; inspect task status before retrying");
        }
    }
}
