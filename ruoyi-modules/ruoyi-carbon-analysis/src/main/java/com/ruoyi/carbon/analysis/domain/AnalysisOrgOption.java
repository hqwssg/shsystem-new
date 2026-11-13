package com.ruoyi.carbon.analysis.domain;

public class AnalysisOrgOption
{
    private Long id;
    private String name;
    private Long parentId;
    private String nodeCategory;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public Long getParentId() { return parentId; }
    public void setParentId(Long parentId) { this.parentId = parentId; }
    public String getNodeCategory() { return nodeCategory; }
    public void setNodeCategory(String nodeCategory) { this.nodeCategory = nodeCategory; }
}
