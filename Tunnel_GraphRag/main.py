import os
import json
import networkx as nx
from typing import List, Dict, Any
from openai import OpenAI
from dotenv import load_dotenv
import community as community_louvain
from pyvis.network import Network
import argparse

# 加载配置
load_dotenv()

client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url=os.getenv("OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
)

# 默认模型选择，优先从环境变量读取
MODEL = os.getenv("MODEL_NAME", "qwen-plus") 

class SimpleGraphRAG:
    def __init__(self, output_dir="output"):
        self.graph = nx.Graph()
        self.output_dir = output_dir
        self.communities = {}
        self.community_summaries = {}
        
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

    def _llm_query(self, prompt: str, system_prompt: str = "你是一个专业的数据分析师。"):
        """封装 LLM 调用"""
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"LLM 调用失败: {e}")
            return ""

    def extract_entities_and_relationships(self, text_chunk: str):
        """核心步骤：从文本中提取实体和关系"""
        prompt = f"""
        请从以下文本中提取所有的实体及其相互关系。
        返回结果必须是 JSON 格式，包含 'entities' (实体列表，每个实体包含 'name' 和 'type') 
        以及 'relationships' (关系列表，每个关系包含 'source', 'target', 'description')。

        文本内容：
        {text_chunk}

        JSON 示例：
        {{
            "entities": [{{ "name": "盾构机", "type": "设备" }}],
            "relationships": [{{ "source": "盾构机", "target": "隧道", "description": "用于挖掘" }}]
        }}
        """
        res = self._llm_query(prompt, system_prompt="你是一个知识图谱专家，只返回 JSON 格式数据。")
        # 简单清洗 JSON
        if "```json" in res:
            res = res.split("```json")[1].split("```")[0].strip()
        try:
            return json.loads(res)
        except:
            return {"entities": [], "relationships": []}

    def process_document(self, file_path: str):
        """处理文档：分段 -> 提取 -> 建图"""
        print(f"正在处理文档: {file_path}")
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 简易分段：按行或固定长度（此处简化为大段处理，实际应精细化）
        chunks = [content] # 简单起见，这里假设文件不大

        for chunk in chunks:
            data = self.extract_entities_and_relationships(chunk)
            
            # 添加实体到图
            for ent in data.get('entities', []):
                self.graph.add_node(ent['name'], type=ent.get('type', 'Unknown'))
            
            # 添加关系到图
            for rel in data.get('relationships', []):
                u, v = rel['source'], rel['target']
                self.graph.add_edge(u, v, description=rel.get('description', ''))

    def build_communities(self):
        """社区发现：使用 Louvain 算法"""
        print("正在进行社区发现...")
        partition = community_louvain.best_partition(self.graph)
        
        for node, comm_id in partition.items():
            if comm_id not in self.communities:
                self.communities[comm_id] = []
            self.communities[comm_id].append(node)
        
        print(f"检测到 {len(self.communities)} 个社区。")

    def summarize_communities(self):
        """为每个社区生成摘要"""
        print("正在生成社区摘要 (Global Search 的基础)...")
        for comm_id, nodes in self.communities.items():
            edges = self.graph.edges(nodes, data=True)
            edge_desc = "\n".join([f"{u} --({d['description']})--> {v}" for u, v, d in edges])
            
            prompt = f"""
            以下是一个知识图谱社区的成员及其关系：
            实体：{', '.join(nodes)}
            关系：
            {edge_desc}
            
            请简洁地总结这个社区代表的主题或业务逻辑。建议不超过200字。
            """
            summary = self._llm_query(prompt)
            self.community_summaries[comm_id] = summary

    def global_search(self, query: str):
        """全局搜索：汇总所有社区摘要进行回答"""
        print(f"执行全局搜索: {query}")
        all_summaries = "\n\n".join([f"社区 {i}: {s}" for i, s in self.community_summaries.items()])
        
        prompt = f"""
        基于以下多份社区摘要，请回答用户的问题。
        
        社区摘要：
        {all_summaries}
        
        用户问题：{query}
        """
        return self._llm_query(prompt)

    def local_search(self, query: str):
        """局部搜索：找到相关节点及其邻居进行回答"""
        print(f"执行局部搜索: {query}")
        # 简单匹配：寻找 Query 中出现的实体
        relevant_nodes = [node for node in self.graph.nodes if node.lower() in query.lower()]
        
        # 扩展一度邻居
        context_nodes = set(relevant_nodes)
        for node in relevant_nodes:
            context_nodes.update(self.graph.neighbors(node))
        
        if not context_nodes:
            return "对不起，在图中未找到相关实体，请尝试全局搜索或更换关键词。"
        
        edges = self.graph.edges(context_nodes, data=True)
        edge_desc = "\n".join([f"{u} --({d['description']})--> {v}" for u, v, d in edges])
        
        prompt = f"""
        基于以下提取的局部图片段，回答用户的问题。
        
        涉及实体：{', '.join(context_nodes)}
        关系：
        {edge_desc}
        
        用户问题：{query}
        """
        return self._llm_query(prompt)

    def visualize(self):
        """使用 Pyvis 生成交互式网页"""
        print("生成可视化图谱...")
        net = Network(height="750px", width="100%", bgcolor="#222222", font_color="white", notebook=False)
        
        for node, attrs in self.graph.nodes(data=True):
            net.add_node(node, label=node, title=attrs.get('type', ''), group=attrs.get('type', ''))
            
        for u, v, attrs in self.graph.edges(data=True):
            net.add_edge(u, v, title=attrs.get('description', ''))
            
        output_path = os.path.join(self.output_dir, "graph_visualization.html")
        net.save_graph(output_path)
        print(f"可视化已保存至: {output_path}")

    def save_state(self):
        """保存中间状态"""
        data = {
            "communities": self.communities,
            "summaries": self.community_summaries,
            "graph_nodes": list(self.graph.nodes(data=True)),
            "graph_edges": list(self.graph.edges(data=True))
        }
        with open(os.path.join(self.output_dir, "graph_state.json"), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_state(self):
        """从本地加载图谱状态"""
        state_path = os.path.join(self.output_dir, "graph_state.json")
        if not os.path.exists(state_path):
            return False
        
        print(f"正在从本地加载索引: {state_path}")
        with open(state_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        self.communities = {int(k): v for k, v in data.get("communities", {}).items()}
        self.community_summaries = {int(k): v for k, v in data.get("summaries", {}).items()}
        
        # 恢复网络图
        for node, attrs in data.get("graph_nodes", []):
            self.graph.add_node(node, **attrs)
        for u, v, attrs in data.get("graph_edges", []):
            self.graph.add_edge(u, v, **attrs)
        
        return True

def main():
    parser = argparse.ArgumentParser(description="Tunnel GraphRAG 简易演示")
    parser.add_argument("--index", action="store_true", help="构建索引")
    parser.add_argument("--query", type=str, help="搜索关键词")
    parser.add_argument("--mode", choices=["global", "local"], default="local", help="搜索模式")
    args = parser.parse_args()

    rag = SimpleGraphRAG()

    if args.index:
        input_file = "input/tunnel_project.txt"
        if os.path.exists(input_file):
            rag.process_document(input_file)
            rag.build_communities()
            rag.summarize_communities()
            rag.visualize()
            rag.save_state()
            print("索引构建成功并已持久化到本地！")
        else:
            print("未找到测试数据 input/tunnel_project.txt")

    if args.query:
        # 优先尝试从本地加载
        if not rag.load_state():
            print("未找到本地索引，请先运行 python main.py --index 构建索引。")
            return

        if args.mode == "global":
            result = rag.global_search(args.query)
        else:
            result = rag.local_search(args.query)
        
        print("\n" + "="*20 + " 搜 索 结 果 " + "="*20)
        print(result)

if __name__ == "__main__":
    main()
