package com.ruoyi.carbon.singletrain;

import java.io.IOException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import com.alibaba.fastjson2.JSON;
import com.ruoyi.common.core.exception.ServiceException;
import com.ruoyi.common.core.utils.PythonServiceClient;

@Component
public class SingleTrainCli {
    @Value("${carbon.single-train.python-executable:${carbon.energy.python-executable:python}}") private String python;
    @Value("${carbon.single-train.workspace-root:${SINGLE_TRAIN_WORKSPACE_ROOT:}}") private String workspace;
    @Value("${carbon.single-train.algorithm-root:${SINGLE_TRAIN_ALGORITHM_ROOT:}}") private String algorithm;
    @Value("${carbon.single-train.result-root:${SINGLE_TRAIN_RESULT_ROOT:}}") private String resultRoot;
    @Value("${carbon.single-train.database-url:${ENERGY_DATABASE_URL:}}") private String database;
    @Value("${carbon.single-train.solve-timeout-seconds:7200}") private int solveTimeout;
    @Value("${spring.datasource.dynamic.datasource.master.url:}") private String jdbc;
    @Value("${spring.datasource.dynamic.datasource.master.username:}") private String username;
    @Value("${spring.datasource.dynamic.datasource.master.password:}") private String password;

    public Path workspace() {
        if (workspace != null && !workspace.isBlank()) return Path.of(workspace).toAbsolutePath().normalize();
        Path p = Path.of("").toAbsolutePath();
        for (int i=0; i<6 && p!=null; i++,p=p.getParent())
            if (Files.isDirectory(p.resolve("single_train_recovery_agent"))) return p;
        throw new ServiceException("请配置 carbon.single-train.workspace-root");
    }
    public Path resultRoot() {
        return resultRoot == null || resultRoot.isBlank() ? workspace().resolve("output/single_train_results") : Path.of(resultRoot).toAbsolutePath().normalize();
    }
    private String databaseUrl() {
        if (database != null && !database.isBlank()) return database;
        String rest=jdbc.startsWith("jdbc:")?jdbc.substring(5):jdbc;
        int query=rest.indexOf('?'); if(query>=0) rest=rest.substring(0,query);
        int scheme=rest.indexOf("://");
        if(scheme<0) throw new ServiceException("单列车模块数据库未配置");
        return rest.substring(0,scheme+3)+URLEncoder.encode(username,StandardCharsets.UTF_8).replace("+","%20")+":"+URLEncoder.encode(password,StandardCharsets.UTF_8).replace("+","%20")+"@"+rest.substring(scheme+3);
    }
    public Object call(String action, String target, Long dept, String user, Object body) {
        Path input=null;
        var readers=Executors.newFixedThreadPool(2);
        Process process=null;
        try {
            Path root=workspace(); Path inputs=root.resolve("output/single_train_requests"); Files.createDirectories(inputs);
            input=Files.createTempFile(inputs,"request-",".json"); Files.writeString(input,JSON.toJSONString(body==null?Map.of():body),StandardCharsets.UTF_8);
            List<String> command=new ArrayList<>(List.of(python,"-m","single_train_recovery_agent.cli",action,"--target",target,"--input-file",input.toString(),"--user",user));
            if(dept!=null) { command.add("--dept");command.add(dept.toString()); }
            Map<String,String> pythonEnv=Map.of("ENERGY_DATABASE_URL", databaseUrl(),
                    "SINGLE_TRAIN_RESULT_ROOT", resultRoot().toString(),
                    "SINGLE_TRAIN_SOLVE_TIMEOUT", Integer.toString(solveTimeout),
                    "SINGLE_TRAIN_ALGORITHM_ROOT", algorithm==null?"":algorithm);
            int timeout=action.equals("work")?solveTimeout+120:180;
            PythonServiceClient.requireConfigured();
            if(PythonServiceClient.enabled()) {
                var result=PythonServiceClient.run(command,root,pythonEnv,java.time.Duration.ofSeconds(timeout),1048576);
                String stdout=result.getString("stdout"),stderr=result.getString("stderr");
                if(result.getIntValue("exitCode")!=0) throw new ServiceException(stderr==null||stderr.isBlank()?"单列车命令失败":stderr.trim());
                return JSON.parse(stdout);
            }
            ProcessBuilder builder=new ProcessBuilder(command);builder.directory(root.toFile());
            builder.environment().put("PYTHONPATH",root.toString());builder.environment().put("PYTHONIOENCODING","utf-8");
            builder.environment().put("ENERGY_DATABASE_URL",databaseUrl());
            builder.environment().put("SINGLE_TRAIN_RESULT_ROOT",resultRoot().toString());
            builder.environment().put("SINGLE_TRAIN_SOLVE_TIMEOUT",Integer.toString(solveTimeout));
            if(algorithm!=null&&!algorithm.isBlank()) builder.environment().put("SINGLE_TRAIN_ALGORITHM_ROOT",algorithm);
            process=builder.start();final Process child=process;
            var out=readers.submit(()->new String(child.getInputStream().readAllBytes(),StandardCharsets.UTF_8));
            var err=readers.submit(()->new String(child.getErrorStream().readAllBytes(),StandardCharsets.UTF_8));
            if(!process.waitFor(timeout,TimeUnit.SECONDS)) {
                process.destroyForcibly();throw new ServiceException("单列车任务命令超时，已完成案例会保留");
            }
            String stdout=out.get(5,TimeUnit.SECONDS),stderr=err.get(5,TimeUnit.SECONDS);
            if(process.exitValue()!=0) throw new ServiceException(stderr.isBlank()?"单列车命令失败":stderr.trim());
            return JSON.parse(stdout);
        } catch(ServiceException ex) {throw ex;}
        catch(Exception ex) {throw new ServiceException("单列车模块执行失败："+ex.getMessage());}
        finally {
            if(process!=null&&process.isAlive()) process.destroyForcibly();readers.shutdownNow();
            if(input!=null) try {Files.deleteIfExists(input);} catch(IOException ignored) {}
        }
    }
}
