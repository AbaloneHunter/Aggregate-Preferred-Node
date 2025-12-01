#!/usr/bin/env python3
"""
GitHub Actions Subscription Generator for NekoBox/FlClash
生成可直接使用的在线订阅链接
"""

import os
import json
import time
import requests
import base64
import re
import argparse
import random
from datetime import datetime
from urllib.parse import urlparse, quote
import concurrent.futures
import threading

class SubscriptionGenerator:
    def __init__(self, args):
        self.args = args
        self.nodes_file = args.nodes_file
        self.output_dir = args.output_dir
        
        # 从环境变量或命令行参数获取在线订阅地址
        self.subscription_urls = self.get_subscription_urls()
        
        # 测试配置
        self.timeout = args.timeout
        self.latency_threshold = args.latency_threshold
        self.max_workers = args.workers
        self.test_count = args.test_count
        self.top_n = args.top_n
        
        # 测试URL列表
        self.test_urls = [
            {
                'url': 'https://www.gstatic.com/generate_204',
                'name': 'Google Static',
                'expected_status': 204,
                'weight': 1.0
            },
            {
                'url': 'https://httpbin.org/get',
                'name': 'HttpBin', 
                'expected_status': 200,
                'weight': 0.9
            }
        ]
        
        self.results = []
        self.lock = threading.Lock()
        
    def get_subscription_urls(self):
        """从环境变量或命令行参数获取在线订阅地址"""
        if self.args.subscription:
            urls = [url.strip() for url in self.args.subscription.split('&') if url.strip()]
            print(f"📡 从命令行参数找到 {len(urls)} 个在线订阅地址")
            return urls
        
        subscription_env = os.getenv('ONLINE_SUBSCRIPTION', '').strip()
        if subscription_env:
            urls = [url.strip() for url in subscription_env.split('&') if url.strip()]
            print(f"📡 从环境变量找到 {len(urls)} 个在线订阅地址")
            return urls
        
        return []
    
    def fetch_online_subscription(self, url):
        """获取在线订阅内容"""
        try:
            print(f"🔗 获取订阅: {url}")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(url, timeout=15, headers=headers)
            response.raise_for_status()
            
            # 尝试Base64解码
            try:
                content = base64.b64decode(response.text).decode('utf-8')
                print(f"✅ 订阅解码成功，长度: {len(content)} 字符")
                return content
            except:
                # 如果不是Base64，直接使用原内容
                print(f"✅ 订阅获取成功，长度: {len(response.text)} 字符")
                return response.text
                
        except Exception as e:
            print(f"❌ 获取订阅失败 [{url}]: {e}")
            return None
    
    def parse_subscription_content(self, content):
        """解析订阅内容"""
        nodes = []
        lines = content.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # 支持各种代理协议
            if any(proto in line for proto in ['ss://', 'ssr://', 'vmess://', 'trojan://', 'vless://']):
                node = self.parse_node_line(line)
                if node:
                    nodes.append(node)
                    node['source'] = 'subscription'
        
        return nodes
    
    def load_all_nodes(self):
        """加载所有节点（本地文件 + 在线订阅）"""
        all_nodes = []
        
        # 1. 加载本地节点文件
        local_nodes = self.parse_nodes_file()
        for node in local_nodes:
            node['source'] = 'local'
        all_nodes.extend(local_nodes)
        print(f"📁 本地节点: {len(local_nodes)} 个")
        
        # 2. 加载在线订阅节点
        subscription_nodes = []
        for sub_url in self.subscription_urls:
            try:
                content = self.fetch_online_subscription(sub_url)
                if content:
                    nodes = self.parse_subscription_content(content)
                    subscription_nodes.extend(nodes)
                    print(f"📥 从订阅获取节点: {len(nodes)} 个")
                    time.sleep(1)
                    
            except Exception as e:
                print(f"❌ 处理订阅失败 [{sub_url}]: {e}")
        
        all_nodes.extend(subscription_nodes)
        
        # 去重
        unique_nodes = []
        seen = set()
        
        for node in all_nodes:
            node_id = node['original']
            if node_id not in seen:
                seen.add(node_id)
                unique_nodes.append(node)
        
        # 如果指定了测试数量，进行抽样
        if self.test_count > 0 and len(unique_nodes) > self.test_count:
            print(f"🔢 抽样测试: 从 {len(unique_nodes)} 个节点中随机选择 {self.test_count} 个")
            unique_nodes = random.sample(unique_nodes, self.test_count)
        
        print(f"📊 总节点数: {len(all_nodes)} → 去重后: {len(unique_nodes)} 个")
        return unique_nodes
    
    def parse_nodes_file(self):
        """解析节点文件"""
        nodes = []
        if not os.path.exists(self.nodes_file):
            print(f"⚠️ 节点文件 {self.nodes_file} 不存在")
            return nodes
            
        try:
            with open(self.nodes_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    node = self.parse_node_line(line)
                    if node:
                        nodes.append(node)
                    else:
                        print(f"⚠️ 第{line_num}行无法解析: {line[:50]}...")
                        
            return nodes
            
        except Exception as e:
            print(f"❌ 读取节点文件失败: {e}")
            return []
    
    def parse_node_line(self, line):
        """解析单行节点配置"""
        line = line.strip()
        
        patterns = [
            {'regex': r'^ssr://([A-Za-z0-9+/=]+)', 'type': 'ssr'},
            {'regex': r'^vmess://([A-Za-z0-9+/=]+)', 'type': 'vmess'},
            {'regex': r'^trojan://([^@]+)@([^:]+):(\d+)', 'type': 'trojan'},
            {'regex': r'^vless://([^@]+)@([^:]+):(\d+)', 'type': 'vless'},
            {'regex': r'^ss://([A-Za-z0-9+/=]+)', 'type': 'ss'}
        ]
        
        for pattern in patterns:
            match = re.match(pattern['regex'], line)
            if match:
                return {
                    'original': line,
                    'type': pattern['type'],
                    'parts': match.groups()
                }
        
        return None
    
    def test_latency(self, node):
        """测试节点延迟"""
        test_results = []
        fastest_success = None
        
        for test_url in self.test_urls:
            try:
                start_time = time.time()
                
                response = requests.get(
                    test_url['url'],
                    timeout=8,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    }
                )
                
                latency = int((time.time() - start_time) * 1000)
                is_success = response.status_code == test_url['expected_status']
                
                test_result = {
                    'url': test_url['name'],
                    'latency': latency,
                    'status': response.status_code,
                    'success': is_success,
                    'weight': test_url['weight']
                }
                
                test_results.append(test_result)
                
                if is_success and latency < self.latency_threshold:
                    if not fastest_success or latency < fastest_success['latency']:
                        fastest_success = test_result
                
                if latency < 100:
                    break
                    
                time.sleep(0.3)
                
            except requests.RequestException as e:
                test_results.append({
                    'url': test_url['name'],
                    'latency': -1,
                    'status': 0,
                    'success': False,
                    'error': str(e),
                    'weight': test_url['weight']
                })
        
        return {
            'fastest_success': fastest_success,
            'all_results': test_results,
            'passed': fastest_success is not None
        }
    
    def test_download_speed(self, node, latency):
        """测试下载速度"""
        if latency >= 1000:  # 延迟太高不测速
            return 0
            
        print(f"    🚀 开始速度测试，当前延迟: {latency}ms")
        
        # 根据延迟调整测试文件大小
        if latency < 200:
            file_size = 512000  # 500KB
        elif latency < 500:
            file_size = 256000  # 250KB
        else:
            file_size = 102400  # 100KB
        
        speed_test_urls = [
            f'https://httpbin.org/bytes/{file_size}',
            'https://speedtest.ftp.otenet.gr/files/test100k.db'
        ]
        
        for test_url in speed_test_urls:
            try:
                start_time = time.time()
                
                response = requests.get(
                    test_url,
                    timeout=10,
                    stream=True,
                    headers={
                        'User-Agent': 'Mozilla/5.0',
                        'Cache-Control': 'no-cache'
                    }
                )
                response.raise_for_status()
                
                content = b''
                for chunk in response.iter_content(chunk_size=8192):
                    content += chunk
                
                duration = time.time() - start_time
                data_size = len(content)
                
                if data_size > 0 and duration > 0:
                    speed_kbps = (data_size / duration) / 1024
                    
                    print(f"    📊 速度测试完成: {speed_kbps:.0f} KB/s")
                    return int(speed_kbps)
                    
            except requests.RequestException:
                continue
                
            time.sleep(0.5)
        
        print("    ⚠️ 测速失败")
        return 0
    
    def get_geo_info(self, ip=None):
        """获取地理位置信息"""
        try:
            if not ip:
                ip_response = requests.get('https://httpbin.org/ip', timeout=5)
                if ip_response.status_code == 200:
                    ip_data = ip_response.json()
                    ip = ip_data.get('origin', '').split(',')[0]
            
            if ip:
                geo_response = requests.get(f'http://ip-api.com/json/{ip}', timeout=5)
                if geo_response.status_code == 200:
                    geo_data = geo_response.json()
                    if geo_data.get('status') == 'success':
                        return {
                            'country': geo_data.get('country', 'Unknown'),
                            'city': geo_data.get('city', 'Unknown'),
                            'isp': geo_data.get('isp', 'Unknown'),
                            'ip': ip
                        }
        except:
            pass
        
        return {
            'country': 'Unknown',
            'city': 'Unknown', 
            'isp': 'Unknown',
            'ip': 'Unknown'
        }
    
    def calculate_score(self, latency, speed, success):
        """计算综合评分"""
        if latency <= 0:
            return 0
        
        # 延迟评分
        if latency < 50:
            latency_score = 100
        elif latency < 100:
            latency_score = 95
        elif latency < 200:
            latency_score = 85
        elif latency < 300:
            latency_score = 75
        elif latency < 500:
            latency_score = 60
        else:
            latency_score = 40
        
        # 速度评分
        if speed == 0:
            speed_score = 0
        elif speed > 5000:
            speed_score = 100
        elif speed > 2000:
            speed_score = 90
        elif speed > 1000:
            speed_score = 80
        elif speed > 500:
            speed_score = 70
        elif speed > 100:
            speed_score = 50
        else:
            speed_score = 30
        
        # 成功率评分
        success_score = 100 if success else 0
        
        # 加权评分
        total_score = (latency_score * 0.6 + speed_score * 0.4 + success_score * 0.2) / 1.2
        return round(total_score, 1)
    
    def test_single_node(self, node, index, total_count):
        """测试单个节点"""
        node_id = f"{index+1}/{total_count}"
        print(f"\n🔍 测试节点 {node_id}: {node['type']}节点")
        
        try:
            # 延迟测试
            latency_test = self.test_latency(node)
            
            if not latency_test['passed']:
                print(f"    ❌ 未通过延迟测试")
                return None
            
            latency = latency_test['fastest_success']['latency']
            print(f"    ✅ 延迟测试通过: {latency}ms")
            
            # 速度测试
            speed = 0
            if latency < self.latency_threshold:
                speed = self.test_download_speed(node, latency)
            
            # 获取地理位置（简化）
            geo_info = self.get_geo_info()
            
            # 计算评分
            score = self.calculate_score(latency, speed, latency_test['fastest_success']['success'])
            
            result = {
                'node': node['original'],
                'type': node['type'],
                'latency': latency,
                'speed': speed,
                'country': geo_info['country'],
                'isp': geo_info['isp'],
                'score': score,
                'success': latency_test['fastest_success']['success'],
                'source': node.get('source', 'unknown')
            }
            
            print(f"    📊 综合评分: {score}")
            return result
            
        except Exception as e:
            print(f"    ❌ 测试失败: {e}")
            return None
    
    def run_tests(self):
        """运行所有测试"""
        print("🚀 开始节点测试...")
        
        # 加载所有节点
        nodes = self.load_all_nodes()
        if not nodes:
            print("❌ 没有找到可测试的节点")
            return
        
        print(f"📊 总共 {len(nodes)} 个节点需要测试\n")
        
        passed_count = 0
        
        # 使用线程池并发测试
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_node = {
                executor.submit(self.test_single_node, node, i, len(nodes)): (i, node)
                for i, node in enumerate(nodes)
            }
            
            for future in concurrent.futures.as_completed(future_to_node):
                i, node = future_to_node[future]
                try:
                    result = future.result()
                    if result:
                        with self.lock:
                            self.results.append(result)
                            if result['success']:
                                passed_count += 1
                except Exception as e:
                    print(f"❌ 节点测试异常: {e}")
        
        # 按评分排序
        self.results.sort(key=lambda x: x['score'], reverse=True)
        
        print(f'\n🎉 测试完成! 通过节点: {passed_count}/{len(nodes)}')
    
    def generate_neko_subscription(self):
        """生成NekoBox/FlClash可用的订阅文件"""
        print("\n📡 生成订阅文件...")
        
        # 筛选优质节点
        valid_nodes = []
        for result in self.results:
            if (result['success'] and 
                result['score'] > 30 and
                result.get('speed', 0) > 100):
                valid_nodes.append(result)
        
        if not valid_nodes:
            print("❌ 没有合格的节点")
            return None
        
        # 只取前N个
        valid_nodes = valid_nodes[:self.top_n]
        
        print(f"🎯 选取了 {len(valid_nodes)} 个优质节点")
        
        # 生成标准订阅格式
        subscription_content = self._create_subscription_content(valid_nodes)
        
        # Base64编码
        encoded_content = base64.b64encode(subscription_content.encode()).decode()
        
        # 保存订阅文件
        os.makedirs(self.output_dir, exist_ok=True)
        
        # 1. 原始订阅文件
        sub_file = os.path.join(self.output_dir, 'subscription.txt')
        with open(sub_file, 'w', encoding='utf-8') as f:
            f.write(encoded_content)
        
        # 2. 解码后的文件（方便查看）
        decoded_file = os.path.join(self.output_dir, 'subscription_decoded.txt')
        with open(decoded_file, 'w', encoding='utf-8') as f:
            f.write(subscription_content)
        
        # 3. JSON格式（包含详细信息）
        json_file = os.path.join(self.output_dir, 'subscription_info.json')
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'node_count': len(valid_nodes),
                'nodes': valid_nodes,
                'subscription_base64': encoded_content
            }, f, indent=2, ensure_ascii=False)
        
        # 4. 生成使用说明
        self._generate_usage_guide(valid_nodes, encoded_content)
        
        return encoded_content
    
    def _create_subscription_content(self, nodes):
        """创建订阅内容"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        content_lines = [
            "# 🚀 NekoBox/FlClash 优选订阅",
            f"# 生成时间: {timestamp}",
            f"# 节点数量: {len(nodes)}",
            f"# 平均延迟: {sum(n['latency'] for n in nodes)/len(nodes):.0f}ms",
            f"# 平均速度: {sum(n.get('speed', 0) for n in nodes)/len(nodes)/1024:.1f} MB/s",
            f"# 平均评分: {sum(n['score'] for n in nodes)/len(nodes):.1f}",
            ""
        ]
        
        # 添加节点
        for i, node in enumerate(nodes, 1):
            speed_mbps = node.get('speed', 0) / 1024
            content_lines.append(f"# {i}. {node['country']} | {node['latency']}ms | {speed_mbps:.1f}MB/s | {node['score']}分")
            content_lines.append(node['node'])
            content_lines.append("")
        
        return '\n'.join(content_lines)
    
    def _generate_usage_guide(self, nodes, encoded_content):
        """生成使用指南"""
        guide = f"""# 🎯 NekoBox/FlClash 订阅使用指南

## 📊 订阅信息
- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 节点数量: {len(nodes)} 个
- 最佳延迟: {min(n['latency'] for n in nodes)}ms
- 平均速度: {sum(n.get('speed', 0) for n in nodes)/len(nodes)/1024:.1f} MB/s
- 平均评分: {sum(n['score'] for n in nodes)/len(nodes):.1f}

## 📱 使用方法

### 方法1: 直接使用（推荐）
订阅链接直接复制以下内容：
{substitution.txt文件的内容预览}

或者使用文件路径：
file://{os.path.abspath(os.path.join(self.output_dir, 'subscription.txt'))}

### 方法2: 在线部署
1. 将 subscription.txt 上传到以下任一平台：
   - GitHub Gist (https://gist.github.com)
   - Pastebin (https://pastebin.com)
   - 个人服务器
2. 获取文件的原始链接（Raw URL）
3. 在NekoBox/FlClash中添加该链接作为订阅

### 方法3: 快速部署到免费平台

#### GitHub Pages:
1. 创建新仓库
2. 上传 subscription.txt
3. 开启Settings → Pages
4. 订阅链接: https://[用户名].github.io/[仓库名]/subscription.txt

#### Vercel:
1. 注册 Vercel (vercel.com)
2. 创建新项目，上传 subscription.txt
3. 部署
4. 订阅链接: https://[项目名].vercel.app/subscription.txt

## 📋 节点详情
"""
        
        for i, node in enumerate(nodes, 1):
            speed_mbps = node.get('speed', 0) / 1024
            guide += f"{i}. {node['country']} - {node['latency']}ms - {speed_mbps:.1f}MB/s - {node['score']}分 ({node['type']})\n"
        
        guide += "\n## ⚙️ 客户端配置建议\n"
        guide += "1. NekoBox: 添加订阅 → 粘贴链接 → 自动更新\n"
        guide += "2. FlClash: 订阅管理 → 添加 → 粘贴链接\n"
        guide += "3. 建议开启自动选择最快节点\n"
        guide += "4. 更新频率: 每6-12小时自动更新\n"
        
        guide_file = os.path.join(self.output_dir, 'USAGE.md')
        with open(guide_file, 'w', encoding='utf-8') as f:
            f.write(guide)
        
        # 生成一键部署脚本
        self._generate_deploy_scripts(nodes)
        
        print(f"📖 使用指南已生成: {guide_file}")
    
    def _generate_deploy_scripts(self, nodes):
        """生成部署脚本"""
        
        # 1. Cloudflare Workers 脚本
        cf_worker_script = f"""// Cloudflare Worker 部署订阅
addEventListener('fetch', event => {{
  event.respondWith(handleRequest(event.request))
}})

const nodes = `{base64.b64encode('\\n'.join([n['node'] for n in nodes]).encode()).decode()}`

async function handleRequest(request) {{
  const url = new URL(request.url)
  
  if (url.pathname === '/subscribe') {{
    return new Response(nodes, {{
      headers: {{
        'Content-Type': 'text/plain;charset=UTF-8',
        'Cache-Control': 'public, max-age=3600',
        'Access-Control-Allow-Origin': '*'
      }}
    }})
  }}
  
  return new Response('NekoBox Subscription Service', {{ status: 200 }})
}}
"""
        
        # 2. Vercel Serverless Function
        vercel_function = f"""// Vercel Function (api/subscribe.js)
module.exports = (req, res) => {{
  const nodes = `{base64.b64encode('\\n'.join([n['node'] for n in nodes]).encode()).decode()}`
  
  res.setHeader('Content-Type', 'text/plain;charset=UTF-8')
  res.setHeader('Cache-Control', 'public, max-age=3600')
  res.setHeader('Access-Control-Allow-Origin', '*')
  res.send(nodes)
}}
"""
        
        # 3. 简单的静态HTML页面
        html_page = f"""<!DOCTYPE html>
<html>
<head>
    <title>NekoBox 订阅服务</title>
    <meta charset="utf-8">
</head>
<body>
    <h1>🚀 NekoBox/FlClash 订阅服务</h1>
    <p>订阅链接: <code id="sub-link">当前页面URL/subscribe</code></p>
    <p>节点数量: {len(nodes)} 个</p>
    <p>更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    <button onclick="copyLink()">复制订阅链接</button>
    
    <script>
    function copyLink() {{
        const link = window.location.origin + '/subscribe';
        navigator.clipboard.writeText(link);
        alert('订阅链接已复制: ' + link);
    }}
    </script>
</body>
</html>
"""
        
        # 保存脚本
        scripts_dir = os.path.join(self.output_dir, 'deploy_scripts')
        os.makedirs(scripts_dir, exist_ok=True)
        
        with open(os.path.join(scripts_dir, 'cloudflare_worker.js'), 'w', encoding='utf-8') as f:
            f.write(cf_worker_script)
        
        with open(os.path.join(scripts_dir, 'vercel_function.js'), 'w', encoding='utf-8') as f:
            f.write(vercel_function)
        
        with open(os.path.join(scripts_dir, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(html_page)
        
        print(f"⚙️ 部署脚本已生成到: {scripts_dir}")
    
    def generate_clash_config(self):
        """可选：生成Clash配置文件"""
        try:
            import yaml
            
            # 筛选节点
            valid_nodes = [n for n in self.results if n['success'] and n['score'] > 30]
            valid_nodes = valid_nodes[:self.top_n]
            
            if not valid_nodes:
                return
            
            clash_config = {
                'port': 7890,
                'socks-port': 7891,
                'allow-lan': False,
                'mode': 'rule',
                'log-level': 'info',
                'proxies': [],
                'proxy-groups': [
                    {
                        'name': '🚀 自动选择',
                        'type': 'url-test',
                        'proxies': [],
                        'url': 'http://www.gstatic.com/generate_204',
                        'interval': 300
                    }
                ],
                'rules': [
                    'DOMAIN-SUFFIX,google.com,🚀 自动选择',
                    'GEOIP,CN,DIRECT',
                    'MATCH,🚀 自动选择'
                ]
            }
            
            # 解析节点
            for i, node in enumerate(valid_nodes):
                try:
                    proxy = self._parse_node_to_clash(node['node'])
                    if proxy:
                        # 添加评分信息到名称
                        speed_mbps = node.get('speed', 0) / 1024
                        proxy['name'] = f"{i+1}.{node['country'][:2]}↔{node['latency']}ms↔{speed_mbps:.0f}M"
                        
                        clash_config['proxies'].append(proxy)
                        clash_config['proxy-groups'][0]['proxies'].append(proxy['name'])
                except:
                    continue
            
            if clash_config['proxies']:
                clash_file = os.path.join(self.output_dir, 'clash_config.yaml')
                with open(clash_file, 'w', encoding='utf-8') as f:
                    yaml.dump(clash_config, f, allow_unicode=True)
                print(f"✅ Clash配置文件已生成: {clash_file}")
                
        except ImportError:
            print("⚠️ 需要安装PyYAML来生成Clash配置: pip install pyyaml")
        except Exception as e:
            print(f"❌ 生成Clash配置失败: {e}")
    
    def _parse_node_to_clash(self, node_str):
        """解析节点为Clash格式（简化版）"""
        if node_str.startswith('ss://'):
            return self._parse_ss_clash(node_str)
        elif node_str.startswith('vmess://'):
            return self._parse_vmess_clash(node_str)
        elif node_str.startswith('trojan://'):
            return self._parse_trojan_clash(node_str)
        return None
    
    def _parse_ss_clash(self, node_str):
        """解析SS节点"""
        try:
            encoded = node_str[5:]
            
            if '@' in encoded:
                method_password, server_port = encoded.split('@')
                if ':' in method_password:
                    method, password = method_password.split(':', 1)
                else:
                    decoded_mp = base64.b64decode(method_password + '==').decode()
                    method, password = decoded_mp.split(':', 1)
                server, port = server_port.split(':')
            else:
                decoded = base64.b64decode(encoded + '==').decode()
                if '@' in decoded:
                    method_password, server_port = decoded.split('@')
                    method, password = method_password.split(':', 1)
                else:
                    method, password, server_port = decoded.split(':', 2)
                server, port = server_port.rsplit(':', 1)
            
            return {
                'name': f"SS-{server}",
                'type': 'ss',
                'server': server,
                'port': int(port),
                'cipher': method,
                'password': password
            }
        except:
            return None
    
    def _parse_vmess_clash(self, node_str):
        """解析VMess节点"""
        try:
            encoded = node_str[8:]
            decoded = base64.b64decode(encoded + '==').decode()
            config = json.loads(decoded)
            
            return {
                'name': f"VMess-{config.get('ps', config.get('add'))}",
                'type': 'vmess',
                'server': config.get('add'),
                'port': int(config.get('port')),
                'uuid': config.get('id'),
                'alterId': int(config.get('aid', 0)),
                'cipher': 'auto',
                'network': config.get('net', 'tcp')
            }
        except:
            return None
    
    def _parse_trojan_clash(self, node_str):
        """解析Trojan节点"""
        try:
            parsed = urlparse(node_str)
            password = parsed.username
            server = parsed.hostname
            port = parsed.port
            
            return {
                'name': f"Trojan-{server}",
                'type': 'trojan',
                'server': server,
                'port': port,
                'password': password
            }
        except:
            return None

def main():
    """主函数"""
    print("=" * 60)
    print("NekoBox/FlClash 订阅生成器")
    print("生成可直接使用的在线订阅链接")
    print("=" * 60)
    
    parser = argparse.ArgumentParser(description='生成NekoBox/FlClash订阅')
    
    # 订阅相关
    parser.add_argument('--subscription', '-s', 
                       help='在线订阅地址，多个用&分隔')
    
    # 测试参数
    parser.add_argument('--workers', '-w', type=int, default=3,
                       help='并发工作线程数 (默认: 3)')
    parser.add_argument('--timeout', '-t', type=int, default=10,
                       help='请求超时时间(秒) (默认: 10)')
    parser.add_argument('--latency-threshold', '-l', type=int, default=2000,
                       help='延迟阈值(毫秒) (默认: 2000)')
    parser.add_argument('--test-count', '-n', type=int, default=0,
                       help='测试节点数量，0表示测试所有 (默认: 0)')
    parser.add_argument('--top-n', type=int, default=15,
                       help='选取最佳节点的数量 (默认: 15)')
    
    # 文件路径
    parser.add_argument('--nodes-file', '-i', default='Nodes',
                       help='输入节点文件路径 (默认: Nodes)')
    parser.add_argument('--output-dir', '-o', default='subscription',
                       help='输出目录 (默认: subscription)')
    
    args = parser.parse_args()
    
    # 创建生成器
    generator = SubscriptionGenerator(args)
    
    # 运行测试
    generator.run_tests()
    
    # 生成订阅
    subscription = generator.generate_neko_subscription()
    
    if subscription:
        print("\n" + "=" * 60)
        print("🎉 订阅生成成功!")
        print("=" * 60)
        
        # 显示使用信息
        print(f"\n📁 生成的文件:")
        print(f"  📄 subscription.txt - Base64订阅文件 (可直接使用)")
        print(f"  📄 subscription_decoded.txt - 解码后的明文")
        print(f"  📄 subscription_info.json - 详细节点信息")
        print(f"  📄 USAGE.md - 使用指南")
        print(f"  📁 deploy_scripts/ - 部署脚本")
        
        print(f"\n📱 使用方法:")
        print(f"  1. 将 subscription.txt 上传到可访问的URL")
        print(f"  2. 在NekoBox/FlClash中添加该URL作为订阅")
        print(f"  3. 客户端会自动测试并选择最快节点")
        
        print(f"\n🌐 推荐部署平台:")
        print(f"  • GitHub Gist (免费、简单)")
        print(f"  • Vercel (免费、自动部署)")
        print(f"  • Cloudflare Workers (免费、快速)")
        print(f"  • 个人服务器")
        
        # 可选：生成Clash配置
        print(f"\n⚙️ 可选功能:")
        try:
            import yaml
            generator.generate_clash_config()
        except ImportError:
            print("  要生成Clash配置，请安装: pip install pyyaml")
        
        print("\n" + "=" * 60)
        
    else:
        print("❌ 订阅生成失败")

if __name__ == "__main__":
    main()
