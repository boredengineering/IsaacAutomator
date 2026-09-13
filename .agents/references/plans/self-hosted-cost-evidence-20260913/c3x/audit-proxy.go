// Transparent trial recorder: forwards unchanged to the real local pricing API.
package main
import("bytes";"encoding/json";"io";"net/http";"net/http/httputil";"net/url";"os")
func main(){u,_:=url.Parse("http://isaac-cost-c3x-api:4000");p:=httputil.NewSingleHostReverseProxy(u);http.ListenAndServe(":4001",http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){b,_:=io.ReadAll(r.Body);r.Body=io.NopCloser(bytes.NewReader(b));json.NewEncoder(os.Stdout).Encode(map[string]string{"method":r.Method,"path":r.URL.String(),"host":r.Host,"body":string(b),"forward_to":u.String()});p.ServeHTTP(w,r)}))}
