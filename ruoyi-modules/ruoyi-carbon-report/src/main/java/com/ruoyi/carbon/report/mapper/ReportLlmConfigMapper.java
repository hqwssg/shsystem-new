package com.ruoyi.carbon.report.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface ReportLlmConfigMapper
{
    String selectValue(@Param("configKey") String configKey);

    int updateValue(@Param("configKey") String configKey, @Param("configValue") String configValue,
            @Param("username") String username);

    int insertValue(@Param("configName") String configName, @Param("configKey") String configKey,
            @Param("configValue") String configValue, @Param("username") String username,
            @Param("remark") String remark);
}
