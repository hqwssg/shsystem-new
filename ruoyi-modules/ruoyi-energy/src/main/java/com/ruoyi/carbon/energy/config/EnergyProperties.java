package com.ruoyi.carbon.energy.config;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import com.ruoyi.common.core.exception.ServiceException;

@Component
public class EnergyProperties
{
    @Value("${carbon.energy.python-executable:${ENERGY_PYTHON:python}}")
    private String pythonExecutable;

    @Value("${carbon.energy.project-root:${ENERGY_PROJECT_ROOT:}}")
    private String projectRoot;

    @Value("${carbon.energy.upload-dir:${ENERGY_UPLOAD_DIR:./uploadPath/energy}}")
    private String uploadDir;

    @Value("${carbon.energy.timeout-seconds:${ENERGY_CLI_TIMEOUT:300}}")
    private int timeoutSeconds;

    @Value("${carbon.energy.solve-timeout-seconds:${ENERGY_SOLVE_TIMEOUT:1800}}")
    private int solveTimeoutSeconds;

    @Value("${carbon.energy.database-url:${ENERGY_DATABASE_URL:}}")
    private String databaseUrl;

    @Value("${carbon.energy.resource-profile:standard}")
    private String resourceProfile;

    @Value("${spring.datasource.dynamic.datasource.master.url:}")
    private String jdbcUrl;

    @Value("${spring.datasource.dynamic.datasource.master.username:}")
    private String jdbcUsername;

    @Value("${spring.datasource.dynamic.datasource.master.password:}")
    private String jdbcPassword;

    public String getPythonExecutable()
    {
        return pythonExecutable;
    }

    public String getProjectRoot()
    {
        return projectRoot;
    }

    public String getUploadDir()
    {
        return uploadDir;
    }

    public int getTimeoutSeconds()
    {
        return timeoutSeconds;
    }

    public int getSolveTimeoutSeconds()
    {
        return solveTimeoutSeconds;
    }

    public String getResourceProfile()
    {
        return resourceProfile == null || resourceProfile.isBlank() ? "standard" : resourceProfile;
    }

    public String resolveDatabaseUrl()
    {
        if (databaseUrl != null && !databaseUrl.isBlank())
        {
            return databaseUrl.trim();
        }
        return fromJdbc(jdbcUrl, jdbcUsername, jdbcPassword);
    }

    static String fromJdbc(String jdbcUrl, String username, String password)
    {
        if (jdbcUrl == null || jdbcUrl.isBlank())
        {
            throw new ServiceException("未配置 carbon.energy.database-url / ENERGY_DATABASE_URL");
        }
        String rest = jdbcUrl.startsWith("jdbc:") ? jdbcUrl.substring(5) : jdbcUrl;
        int query = rest.indexOf('?');
        String base = query < 0 ? rest : rest.substring(0, query);
        int scheme = base.indexOf("://");
        if (scheme < 0)
        {
            throw new ServiceException("无法从 JDBC 构造 ENERGY_DATABASE_URL");
        }
        String user = username == null ? "" : username;
        String pass = password == null ? "" : password;
        String auth = URLEncoder.encode(user, StandardCharsets.UTF_8) + ":"
                + URLEncoder.encode(pass, StandardCharsets.UTF_8) + "@";
        return base.substring(0, scheme + 3) + auth + base.substring(scheme + 3);
    }
}
