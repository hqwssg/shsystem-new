package com.ruoyi.carbon.energy.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.junit.jupiter.api.Assumptions.assumeTrue;
import static org.mockito.Mockito.mock;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.apache.ibatis.builder.xml.XMLMapperBuilder;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.Configuration;
import org.apache.ibatis.session.SqlSessionFactoryBuilder;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import com.alibaba.fastjson2.JSON;
import com.mysql.cj.jdbc.MysqlDataSource;
import com.ruoyi.carbon.energy.cli.EnergyCliClient;
import com.ruoyi.carbon.energy.config.EnergyProperties;
import com.ruoyi.carbon.energy.mapper.EnergyMapper;
import com.ruoyi.carbon.energy.service.impl.EnergyServiceImpl;

class StoragePlanningMapperIntegrationTest
{
    @Test
    void mapperQueriesAndServiceResponseAgainstOwnedIsolatedMysql() throws Exception
    {
        String setting = System.getProperty("energy.isolated.audit");
        assumeTrue(setting != null, "Explicit isolated instance path required; business datasource is never used.");
        Path audit = Path.of(setting).toAbsolutePath().normalize();
        var state = JSON.parseObject(Files.readString(audit.resolve("isolated_mysql/instance.json")));
        var report = JSON.parseObject(Files.readString(audit.resolve("mysql_validation.json")));
        int port = state.getIntValue("port");
        assertTrue(port > 1024 && port != 3306);
        var datasource = new MysqlDataSource();
        datasource.setURL("jdbc:mysql://127.0.0.1:" + port + "/energy_isolated?useSSL=false&serverTimezone=UTC&characterEncoding=utf8");
        datasource.setUser("root");
        datasource.setPassword("");
        try (var connection = datasource.getConnection(); var statement = connection.createStatement(); var rows = statement.executeQuery("SELECT @@datadir, DATABASE()"))
        {
            assertTrue(rows.next());
            assertEquals(audit.resolve("isolated_mysql/data").toRealPath(), Path.of(rows.getString(1)).toRealPath());
            assertEquals("energy_isolated", rows.getString(2));
        }
        var configuration = new Configuration();
        configuration.setEnvironment(new Environment("owned-isolated-only", new JdbcTransactionFactory(), datasource));
        try (var stream = getClass().getResourceAsStream("/mapper/carbon/energy/EnergyMapper.xml"))
        {
            new XMLMapperBuilder(stream, configuration, "EnergyMapper.xml", configuration.getSqlFragments()).parse();
        }
        try (var session = new SqlSessionFactoryBuilder().build(configuration).openSession())
        {
            var mapper = session.getMapper(EnergyMapper.class);
            String runId = report.getString("api_run_id");
            assertEquals("storage_planning", mapper.selectRun(runId).get("runType"));
            assertTrue(mapper.countStoragePlans(runId) > 1);
            assertEquals(1, mapper.selectStoragePlans(runId, 1, 1).size());
            assertNull(mapper.selectStoragePlan(runId, "foreign-plan-id"));
            var decision = mapper.selectStoragePlanningDecision(runId);
            assertEquals("recommend_build", decision.get("decision"));
            String selectedId = String.valueOf(decision.get("selectedStoragePlanId"));
            assertFalse(mapper.selectStoragePlanDevices(selectedId).isEmpty());
            assertFalse(mapper.selectStoragePlanScenarios(selectedId).isEmpty());
            var service = new EnergyServiceImpl(mapper, mock(EnergyCliClient.class), new EnergyProperties(), Runnable::run);
            var body = service.storagePlanning(null, runId, selectedId, 1, 20);
            assertEquals(Boolean.FALSE, body.get("referenceOnly"));
            assertTrue(((Map<?, ?>)((Map<?, ?>)body.get("decision")).get("details")).containsKey("declaredSearchDomain"));
        }
    }
}
